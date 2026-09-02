"""Structured logs, counters, and upstream health state.

The README asks that an operator be able to answer three questions from
this service's logs and metrics alone. Each question maps to one event type:

1. Is the upstream healthy, slow, or failing right now?
   Every real upstream attempt logs an `upstream_fetch` line with its
   outcome and latency. GET /healthz summarizes a rolling window as
   healthy, slow, degraded, or failing. GET /metrics has upstream.* counters.
2. Was this page served from cache or fetched fresh?
   Every served request logs a `request` line whose `cache` field is one of
   fresh, stale-timeout, stale-error, or miss. It is the same value as the
   response's X-Cache header. The request.* counters aggregate it.
3. Did a correction propagate, and when?
   A `correction_propagated` line is logged with the old and new version
   the moment a fetched version replaces the cached one. Its timestamp is
   the propagation time. There is also a corrections_propagated counter.

Design (D-010): the standard library logger writes one JSON object per line
to stdout, and metrics are in-process counters served as JSON. There is no
structlog and no Prometheus text format because nothing scrapes this
service; the operator is a person with curl. In production the same field
names would become Datadog log attributes and custom metrics through the
agent. README-SERVICE.md covers that.
"""

import json
import logging
import time
from collections import Counter, deque
from datetime import UTC, datetime

logger = logging.getLogger("content_service")

# Outcomes that count against upstream health. `ok` is healthy, and so is
# `not_found`: a 404 is the upstream answering correctly (D-008).
FAILURE_OUTCOMES = {"timeout", "unreachable", "http_error", "invalid"}


def _configure_logging() -> None:
    if logger.handlers:  # already configured; uvicorn --reload re-runs this
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields: object) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    logger.info(json.dumps(payload))


class Observability:
    """Counters plus a rolling window of recent upstream attempts.

    The window is small, ten attempts by default, because the question is
    what the upstream is doing right now, and ten attempts answer that
    without turning this into a time-series store. The thresholds in
    upstream_state are judgment calls sized for this exercise. In
    production this class would be replaced by Datadog monitors over
    rates, where thresholds can change without a deploy.
    """

    def __init__(self, recent_window: int = 10, slow_ms: float = 1000.0) -> None:
        _configure_logging()
        self._started = time.monotonic()
        self.counters: Counter[str] = Counter()
        self.recent: deque[dict] = deque(maxlen=recent_window)
        # Successful attempts slower than this count as `slow` (D-015).
        self._slow_ms = slow_ms

    # -- recording ----------------------------------------------------------

    def record_upstream(self, endpoint: str, outcome: str, ms: float) -> None:
        self.counters[f"upstream.{outcome}"] += 1
        self.recent.append({"outcome": outcome, "ms": round(ms, 1)})
        log_event("upstream_fetch", endpoint=endpoint, outcome=outcome, ms=round(ms, 1))

    def record_request(
        self,
        path: str,
        source: str | None,
        cache: str,
        status: int,
        ms: float,
        version: str | None,
    ) -> None:
        self.counters[f"request.{cache}"] += 1
        log_event(
            "request",
            path=path,
            source=source,
            cache=cache,
            status=status,
            ms=round(ms, 1),
            version=version,
        )

    def record_propagation(self, path: str, old_version: int, new_version: int) -> None:
        self.counters["corrections_propagated"] += 1
        log_event(
            "correction_propagated",
            path=path,
            old_version=old_version,
            new_version=new_version,
        )

    # -- reading ------------------------------------------------------------

    def upstream_state(self) -> dict:
        attempts = list(self.recent)
        failures = [a for a in attempts if a["outcome"] in FAILURE_OUTCOMES]
        slow = [
            a for a in attempts if a["outcome"] not in FAILURE_OUTCOMES and a["ms"] >= self._slow_ms
        ]
        if not attempts:
            state = "unknown"
        elif len(failures) == len(attempts) and len(attempts) >= 3:
            state = "failing"
        elif failures:
            state = "degraded"
        elif slow:
            state = "slow"
        else:
            state = "healthy"
        return {"state": state, "recent_attempts": attempts}

    def metrics_snapshot(self) -> dict:
        return {
            "uptime_s": round(time.monotonic() - self._started, 1),
            "counters": dict(sorted(self.counters.items())),
        }
