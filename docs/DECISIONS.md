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

## D-005: Timeout budget of about 1s total, 200ms to connect (accepted; amended by D-015)
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
Amended by D-015: the one-second figure is now the reader's deadline, enforced
in main.py. The httpx client timeout is a separate, longer give-up bound.

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

## D-011: Tests fake the CMS with httpx.MockTransport; no respx, no sleeping (accepted)
Date: 2026-08-31
Context: the failure-mode behaviors need regression tests. The plan originally
penciled in respx for httpx mocking.
Options: (a) respx; (b) httpx's built-in MockTransport with a FakeCms of about
fifty lines that mirrors the mock CMS contract; (c) run the real mock CMS in
the tests.
Choice: (b).
Why: MockTransport gives the same interception with no new dependency (D-001),
and the fake raises httpx.ReadTimeout instead of sleeping through a real
budget, so the timeout paths test in milliseconds. The tests exercise the real
app, client, cache, and coalescer through ASGITransport. Only the transport is
fake. ASGITransport skips the lifespan, so the fixture wires app.state itself.
Option (c) would tie test timing to real sleeps (the slow mode takes 8s) and to
the package we are not allowed to modify. The cost is that FakeCms could drift
from the real CMS contract. That is acceptable because the contract is four
fields and four modes, and the manual browser checklist still runs against the
real thing.
Revisit when: the CMS contract grows.

## D-012: Startup cache warming is built; the production version looks different (accepted; amended by D-015)
Date: 2026-08-31
Context: an empty cache plus a failing upstream is the one case that still
returns 503 (D-007). When does warming help? Only when the CMS is healthy at
startup but fails before an article's first request. That case is common: we
redeploy this service, which empties its cache, far more often than the CMS
goes down.
Choice: a best-effort sequential warm of the index and all articles during
lifespan startup, logged as cache_warmed or cache_warming_skipped. Any failure
means starting with an empty cache, never a failed startup. It blocks startup
for about half a second at this scale.
Why: about twenty lines for a real reduction of the only remaining 503 window,
and it demos well: restart the service and /healthz immediately shows
articles_cached=4.
Production differences, in order of preference: (1) a persistent or shared
cache tier (Redis or disk) so new instances start warm by definition; at
500,000 articles nobody walks the catalog. (2) Rolling deploys plus a readiness
probe that holds traffic until the instance is warm, so no reader reaches a
cold instance. (3) If warming at all, warm only the hot set, for example the
top N paths from CDN logs, since article traffic is heavily concentrated at the
head.
Revisit when: the catalog grows or instances multiply. Switch to (1).
Amended by D-015: warming now runs as a background task instead of blocking
startup, because the client timeout became ten seconds and a hung CMS at
startup would otherwise delay startup by most of a minute.

## D-013: Circuit breaker; considered and deferred (deferred)
Date: 2026-08-31
Context: during a sustained upstream failure, each wave of requests still pays
one coalesced probe. For timeout-shaped failures (hang, slow) that probe costs
the full budget of about a second, felt by whoever is riding the coalesced
fetch.
Why deferred: at this scale the probe cost is bounded and small, one probe per
article per wave thanks to singleflight. A breaker would be the most complex
state machine in the codebase (closed, open, half-open, thresholds to defend,
recovery probes), and a buggy breaker is worse than none. The pattern matters
at production scale as much for the upstream as for the reader: a struggling
CMS needs less traffic, not a probe per article. Production shape: open after
N consecutive failures per upstream, not per article; serve stale immediately
while open; allow a single probe after a cooldown; tune the thresholds from
outage data in Datadog.
Revisit when: there is real traffic, or an upstream whose failure mode is slow
rather than fast.

## D-014: Negative caching (caching 404s); considered and rejected for a media site (deferred)
Date: 2026-08-31
Context: article sites take heavy 404 traffic from dead links, crawlers, and
"hot 404s" from viral bad links. Each 404 currently costs an upstream fetch.
Why rejected here: the highest-traffic moment of an article's life is the
seconds after publish. A 404 cached even 60 seconds earlier, for example by a
crawler probing the about-to-publish path, would hide a brand-new article from
its own launch traffic. That is the worst possible reader to fail. In this
exercise the catalog is fixed, nothing is ever newly published, and 404 volume
is not tested, so the code would prove nothing while adding a second cache
with different invalidation rules from the article cache.
Production shape if built: a TTL of a few seconds, purge-on-publish driven by
CMS events, and scope limited to paths that have 404'd repeatedly rather than
every miss.
Revisit when: production, with publish events available to purge against.

## D-015: The reader's deadline is separate from the fetch's lifetime (accepted; amends D-005 and D-012)
Date: 2026-09-02
Context: with a single one-second timeout, a slow CMS response was cancelled
at one second and thrown away. That is fine for the reader, who gets the
stored copy, but the cache never learns what the slow response contained.
Under a CMS that stays slow, a correction published during the slowdown could
not propagate at all, which contradicts the requirement that readers get the
corrected version under every failure mode. Found while rehearsing the
design review; not caught during the build.
Options: (a) keep one timeout and accept the gap; (b) raise the timeout so
slow responses complete, making readers wait for them; (c) two numbers: the
reader waits up to one second, the fetch may run up to ten, and a fetch that
outlives the reader still writes the cache when it finishes.
Choice: (c).
Why: a slow response is still a good response. The reader should not wait
for it, but the cache should receive it. The fetch already runs as a task
inside SingleFlight, so letting it outlive the reader is a matter of not
cancelling it: the route waits with asyncio.wait rather than wait_for, and
the validate-and-store step moved into the fetch task so it runs regardless
of who is still waiting. Ten seconds is the give-up bound for a true hang.
Two side effects. Warming moved to a background task so a hung CMS at
startup cannot delay startup (amends D-012). /healthz gained a `slow` state,
because a slow CMS now logs `ok` with high latency instead of `timeout`, and
the README asks for healthy, slow, or failing. The cost is that a hung fetch
holds a connection for ten seconds instead of one; coalescing keeps that to
one connection per article and source.
Revisit when: latency data suggests different numbers, or the upstream gains
a way to signal that it is still working, which would make the give-up bound
smarter.
