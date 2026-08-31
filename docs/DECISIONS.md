# Decision Log

Every non-obvious choice in this repo gets a numbered entry here, written when
the choice is made. Commits reference entries as `Decision: D-0xx`. Entries are
never deleted. A reversed decision is marked superseded and a new entry
explains why.

## Template

```
## D-0XX: <short title>            (Status: accepted | superseded by D-0YY | deferred)
Date: YYYY-MM-DD
Context: what problem forced a choice.
Options: the 2-3 real alternatives.
Choice: what we picked.
Why: the reasoning, including what we're trading away.
Revisit when: the condition under which this should be reconsidered.
```

---

## D-001: FastAPI, httpx, and Pydantic; no cache or resilience libraries (accepted)
Date: 2026-08-31
Context: framework and library selection for the content service.
Options: (a) FastAPI and httpx with a hand-written cache; (b) a synchronous
Flask stack; (c) add libraries such as cachetools, aiocache, tenacity, or
pybreaker.
Choice: (a).
Why: FastAPI and uvicorn are already in pyproject.toml and the mock CMS uses
them, so reviewers see one style throughout. The service has to be async to
hold a hung upstream connection without blocking other requests. The README
asks for a cache design from scratch, and a library would hide the part being
assessed. httpx is the one addition; its timeout model is the core safety
mechanism. The cost is that we implement about 100 lines of well-known
patterns ourselves and have to get them right.
Revisit when: this goes to production, where vetted libraries or Redis make
more sense.

## D-002: Revalidate on every request with a time budget; serve the last known good copy on any failure (accepted)
Date: 2026-08-31
Context: freshness policy. Corrections are published directly to the CMS and
this service is not notified. After a correction, every response must be the
corrected version, and the failure modes must still respond quickly.
Options: (a) a TTL cache with a fresh window of, say, 30 seconds; (b)
stale-while-revalidate, which serves the cached copy immediately and refreshes
in the background; (c) revalidate synchronously on every request with a short
timeout, and fall back to the cached copy if that fails.
Choice: (c).
Why: (a) serves the old version for up to a full TTL after a correction, which
fails the assessment's explicit check. (b) serves the old version for exactly
one request after each change. That also fails the "every response" check, and
it fails intermittently, which is worse. (c) is correct on every request and
costs about 100ms when the CMS is healthy, which is the CMS's own latency. The
cost is that no request is served purely from cache while the upstream is
healthy, so the cache does not reduce load on the healthy path. That is fine
at this scale; D-004 covers production.
Revisit when: real traffic arrives (D-004), or the CMS gains push
invalidation.

## D-003: Cache keyed by article path only; store only validated payloads; entries never expire, only get replaced (accepted)
Date: 2026-08-31
Context: cache key and eviction design.
Options: key with or without `source`; expire entries by time, or replace them
only when a newer copy arrives.
Choice: the key is the path. The README says `source` is test tooling, not
part of an article's identity. Only payloads that pass validation are written,
so the `corrupt` mode can never poison the cache. Entries are never evicted by
time. The point of a last-known-good copy is that an old real article is better
than nothing during an outage. An entry is only overwritten by a newer
validated fetch.
Why: a last-known-good copy that expires recreates the empty-cache problem in
the middle of a long outage. Memory is bounded by the size of the catalog,
four articles here. Production would need an LRU bound; that is out of scope
and is discussed in the interview.
Revisit when: the catalog is large enough that memory matters. Then add an LRU
bound and size caps.

## D-004: The production design is different, and is documented rather than built (accepted)
Date: 2026-08-31
Context: this design revalidates on every request. At millions of hits a month
that would put real load on the CMS.
Choice: document the production shape instead of building it: a short TTL or
stale-while-revalidate window of a few seconds; event-driven invalidation,
where a CMS webhook triggers a purge or refresh on publish; a shared cache tier
such as Redis behind the per-instance memory; a CDN in front that honors
stale-while-revalidate and stale-if-error (RFC 5861); and conditional GETs
with ETags if the CMS supported them.
Why: the assessment forbids real infrastructure and does not allow changes to
the CMS, so a webhook receiver is not possible. Building fake versions of
these pieces adds risk without proving anything more.
Revisit when: not applicable. This is interview discussion material.

## D-005: Timeout budget of about 1s total, 200ms to connect (accepted; tune once the cache exists)
Date: 2026-08-31
Context: `slow` takes 8s and `hang` never returns. Healthy is about 100ms. The
budget decides the worst-case page latency when we have a cached copy.
Options: 500ms, 1s, or 2s.
Choice: about 1s total to start; measure and tune, and record the final value
here.
Why: 1s is ten times the healthy latency, so there is little risk of false
timeouts on a local network, and the worst-case page latency is about a
second, which still counts as fast next to an 8s or infinite hang. Production
would set this from a latency histogram, for example p99 times a small
multiplier.
Revisit when: verification shows flakiness, or the reviewers' bar for "fast"
turns out to be stricter.

## D-006: Validation is strict schema plus content checks (accepted)
Date: 2026-08-31
Context: `corrupt` returns HTTP 200 with the right keys but null values for
version, publishedAt, and updatedAt, and `{{placeholder}}` strings for the
text.
Choice: a strict Pydantic model (no missing or null fields; version is an int
of at least 1; dates parse as ISO; body is a non-empty list of non-empty
strings), plus a check that `payload.path` equals the requested path, plus a
rejection of any field containing `{{`.
Why: the schema alone would catch the nulls but not a placeholder headline with
valid types. The path check catches payloads for the wrong article. The cost
is that an overly strict validator could reject legitimate future content. In
production this validator would be versioned alongside the CMS contract.
Revisit when: the CMS contract changes.

## D-007: Empty cache plus a failing upstream returns 503 (accepted; warming deferred)
Date: 2026-08-31
Context: the first request for an article while the upstream is failing has
nothing to fall back to.
Options: (a) a 503 with a clear error body; (b) synthesized placeholder
content; (c) warm the cache at startup.
Choice: (a), with (c) as a later improvement.
Why: invented article content is worse than an error for readers and crawlers
alike. Made-up financial content is a real harm at Fool.com. The Next.js error
boundary gives the reader a retry button.
Revisit when: time allows warming.

## D-008: A CMS 404 is an answer, not a failure; no stale fallback for it (accepted)
Date: 2026-08-31
Context: with a last-known-good cache, what should happen when the CMS returns
404 for an article we have cached?
Options: (a) treat 404 like any failure and serve the cached copy; (b) trust
the 404 and return 404, leaving the cache entry in place; (c) trust the 404
and also delete the cache entry.
Choice: (b).
Why: a 404 is the CMS answering, not failing. In the mock CMS every failure
mode returns before the store lookup, so a 404 always comes from a healthy code
path. Serving a stale copy on 404 would keep unpublished articles, possibly
ones pulled for legal reasons, available indefinitely. That is worse than a
404. The entry is left in place only to avoid deletion logic we do not need.
Nothing serves it while the CMS keeps returning 404, and if the article comes
back a fresh fetch replaces it.
Revisit when: real unpublish or takedown flows exist. Then deletion (c) plus
an explicit purge event would be correct.

## D-009: Coalescing key is path plus source; cache key is path only (accepted)
Date: 2026-08-31
Context: concurrent upstream fetches are now coalesced, because each page view
already makes two identical requests. What counts as "the same fetch"?
Options: (a) coalesce by article path, matching the cache key; (b) coalesce
by path plus the forwarded source parameter.
Choice: (b).
Why: the cache stores articles, and an article's identity is its path. Source
is test tooling and must never affect what is stored or served from cache. A
flight is a fetch, though, and source changes what the upstream will do.
Coalescing by path alone could hand a healthy request the failure result of a
concurrent corrupt-mode fetch, or the reverse. Coalesced callers share
failures on purpose, since one caller paying the timeout budget is the point
of coalescing, and that makes sharing across different sources wrong.
Revisit when: production, where source does not exist. The two keys collapse
into one and (a) becomes correct.

## D-010: Observability is standard-library JSON log lines plus JSON counters; no structlog or Prometheus (accepted)
Date: 2026-08-31
Context: the README requires that logs and metrics alone answer three
questions: is the upstream healthy right now, was this page served from cache
or fetched fresh, and did a correction propagate and when.
Options: (a) structlog and prometheus-client with the exposition format; (b)
standard-library logging that writes one JSON object per line, plus an
in-process Counter served as JSON from /metrics; (c) print statements.
Choice: (b).
Why: nothing scrapes this service in the exercise. The operator is a person
with curl, so the Prometheus text format serves no one, and structlog is a
dependency that does what fifteen lines of standard library do here (D-001).
One JSON object per line on stdout is the twelve-factor shape that Datadog's
agent ingests as-is, and the field names (event, outcome, cache, ms, version)
are chosen to become Datadog log attributes and custom metrics without
renaming. There are three event types, one per README question:
upstream_fetch, logged once per real attempt after coalescing; request, logged
once per served page; and correction_propagated, which carries the old and new
version and whose timestamp is the propagation time. The health state
(healthy, degraded, failing) is a rolling window of ten attempts with
thresholds sized for this exercise. Production would replace that judgment
with Datadog monitors over rates, which can be tuned without a deploy.
Revisit when: something starts scraping, or log volume needs sampling.
