# Content Service

The middle tier this assessment asks for: a FastAPI service on port 8000
between the Next.js app (port 3000) and the mock CMS (port 8001). Design
decisions are recorded in `docs/DECISIONS.md` (D-001 through D-015). Working
conventions are in `AGENTS.md`.

## Run

```bash
npm run dev                                                            # web + cms
uv run uvicorn services.content_service.main:app --port 8000 --reload  # this service
```

## Design in 30 seconds

On every request the service fetches the article from the CMS. The reader
waits up to about one second. If a valid response arrives in time, it is
served and stored as the last known good copy. If the fetch fails, or is still
running at the deadline, the stored copy is served instead. A fetch that
outlives the reader keeps running for up to ten seconds and updates the cache
when it finishes, so a slow CMS still delivers corrections. A 503 is returned
only when there is no stored copy at all.

Freshness comes from revalidating on every request rather than from a TTL,
because corrections are published directly to the CMS and this service is not
notified. Concurrent fetches for the same article are coalesced into one.

## Behavior matrix

| Mode | Upstream outcome | Response (warm cache) | Latency |
|---|---|---|---|
| healthy | 200 valid | fresh, cache updated | ~100ms |
| slow | still running at the 1s deadline; answers at ~8s | last known good (`X-Cache: stale-timeout`); the late answer updates the cache | ~1s |
| down | HTTP 500 | last known good (`X-Cache: stale-error`) | ~100ms |
| hang | still running at the 1s deadline; abandoned at 10s | last known good (`X-Cache: stale-timeout`) | ~1s |
| corrupt | 200, fails validation | last known good (`X-Cache: stale-error`) | ~100ms |
| any, empty cache | as above | 503 (`X-Cache: miss`) | fast |
| unknown path | 404 | 404; never served from cache (D-008) | ~100ms |
| after a correction | 200 valid vN+1 | new version served and cached; propagation logged | ~100ms |

## Observability: the three README questions

The service writes one JSON object per log line to stdout. There are three
event types.

1. **Is the upstream healthy, slow, or failing right now?**
   `{"event": "upstream_fetch", "endpoint": "article", "outcome": "timeout", "ms": 1001.3, ...}`
   One line per real upstream attempt, after coalescing. Outcomes are
   `ok`, `timeout`, `unreachable`, `http_error`, `invalid`, and `not_found`.
   For a summary, `curl localhost:8000/healthz` reports a rolling-window
   verdict of `healthy`, `slow`, `degraded`, `failing`, or `unknown`, along
   with the recent attempts. `slow` means recent attempts succeeded but took
   longer than the reader's deadline.
2. **Was this page served from cache or fetched fresh?**
   `{"event": "request", "path": "/articles/...", "cache": "stale-error", "status": 200, "version": "2", ...}`
   One line per served request. The `cache` field matches the response's
   `X-Cache` header: `fresh`, `stale-timeout`, `stale-error`, or `miss`.
3. **Did a correction propagate, and when?**
   `{"event": "correction_propagated", "path": "...", "old_version": 1, "new_version": 2, "ts": "..."}`
   Logged the moment a fetched version replaces the cached one. The `ts`
   field is the propagation time.

Counters for all of the above are at `curl localhost:8000/metrics`.

## Production notes (the Datadog conversation)

What to measure: request rate and latency histograms (p50, p95, p99) tagged by
cache result; upstream error rate and latency by outcome; the ratio of stale
responses to all responses; and correction propagation lag as a distribution.

What to alert on: symptoms rather than causes. That means a page-latency SLO
burning down, the stale-serve ratio staying above a threshold, or the upstream
reporting `failing` for more than a few minutes.

What to record but not page on: individual timeouts, single 500s, and each
propagation event.

What to leave out: per-request logs at full volume (sample them), and anything
that can be derived from a metric.

The service's log fields (`event`, `outcome`, `cache`, `ms`, `version`) are
named so they can become Datadog log attributes and custom metrics without
renaming (D-010).
