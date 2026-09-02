# For Reviewers

This file is the shortest path to running the service, checking the behavior
the assessment asks about, and finding the reasoning behind each decision.
Every command below is meant to be copied and run as-is.

## How this was built

I used Claude throughout, as the assessment invited. The division of labor was
that I set the process and made the decisions, and Claude drafted code and
documentation inside those constraints.

Before any code was written, I had Claude examine the starter kit and produce
an implementation plan, a decision log, and an `AGENTS.md` that fixed the
rules for the work: never modify `services/mock_cms/`, key the cache by path
only, let only validated payloads into the cache, keep dependencies minimal,
build one phase at a time, and record every non-obvious choice in
`docs/DECISIONS.md` before or with the commit that implements it.

Each phase was then drafted by Claude, after which I read the diff, ran the
verification checklist myself in the browser and the terminal, and only then
committed. The `Verified:` line in each commit message is what I observed. The
design decisions were mine: which stretch items to build and which to defer
came out of my questions about what makes sense for an article site, and the
reasoning in D-012 through D-014 reflects that. After the build I worked
through practice extensions on separate branches to make sure I could modify
any part of the service without help. Finally I had the prose in the docs and
comments rewritten into plain engineering language, with a syntax-tree
comparison proving that no executable code changed. Commits that include
Claude-drafted work carry a `Co-Authored-By` trailer.

## Where the changes are

The first commit, `35c529a`, is the starter kit exactly as received. Everything
after it is my work:

```bash
git log --oneline            # one commit per phase, each message says why
git diff 35c529a --stat      # every file I added or changed
```

The service lives in `services/content_service/` (five files, about 500 lines
including comments). Tests are in `tests/`. The reasoning is in
`docs/DECISIONS.md` (D-001 through D-014), and `README-SERVICE.md` has the
behavior matrix and the observability guide. The only change outside those
places is `httpx` added to `pyproject.toml`. Nothing in `services/mock_cms/`
or the Next.js app was modified.

## Starting the project

Requirements: Node 20+, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and two terminals.

```bash
# Terminal 1: the Next.js app (port 3000) and the mock CMS (port 8001)
npm install
npm run dev

# Terminal 2: the content service (port 8000)
uv run uvicorn services.content_service.main:app --port 8000
```

On startup the service warms its cache from the CMS; the second terminal will
show a `cache_warmed` log line with `"articles": 4`. Open
http://localhost:3000 to see the article list. Note that the mock CMS stores
articles in memory, so corrections are reset whenever `npm run dev` restarts.

## Running the tests

```bash
uv run pytest -q          # 24 tests, under one second
uv run ruff check .       # lint
```

The tests run the real app against a fake CMS at the httpx transport layer, so
they need no running servers. See `tests/conftest.py` and D-011.

## Walking through the checks in the README

Set an article path once so the commands below can be pasted. The four seeded
paths are listed on the home page; this is one of them:

```bash
ARTICLE=investing/2026/07/23/invest-10000-nvidia-stock-10-years-ago-how-much
```

### 1. A healthy request

```bash
curl -si "localhost:8000/articles/$ARTICLE" | grep -iE "^HTTP|^x-cache|^x-article-version"
```

Expect `HTTP/1.1 200`, `x-cache: fresh`, and `x-article-version: 1`. The
service fetched from the CMS, validated the payload, stored it, and served it.

### 2. Each failure mode

The `source` parameter tells the mock CMS how to fail. The service forwards it
and falls back to its stored copy. `time` shows the latency.

```bash
for mode in slow down hang corrupt; do
  echo "== $mode"
  time curl -si "localhost:8000/articles/$ARTICLE?source=$mode" \
    | grep -iE "^HTTP|^x-cache|^x-article-version"
done
```

What to look for:

| mode | status | x-cache | time |
|---|---|---|---|
| slow | 200 | stale-timeout | about 1s (the budget), not the CMS's 8s |
| down | 200 | stale-error | about 100ms |
| hang | 200 | stale-timeout | about 1s, not forever |
| corrupt | 200 | stale-error | about 100ms |

In every case the body is the real article, and the version matches the
healthy request. The same checks work in the browser: open an article and use
the toolbar at the bottom of the page to switch modes.

### 3. Publish a correction, then repeat

```bash
curl -s -X POST "localhost:3000/api/cms/admin?publish-correction=$ARTICLE"
```

That bumps the article to version 2 in the CMS. The next healthy request picks
it up, and the second terminal logs a `correction_propagated` line:

```bash
curl -si "localhost:8000/articles/$ARTICLE" | grep -iE "^x-cache|^x-article-version"
curl -s "localhost:8000/articles/$ARTICLE" | python3 -c "import json,sys; print(json.load(sys.stdin)['body'][0])"
```

Expect `x-article-version: 2` and a first paragraph beginning
`Correction (v2)`. Now rerun the failure-mode loop from step 2. Every mode
should still return 200, still be fast, and now show `x-article-version: 2`.
The stored copy is the corrected one, because the healthy request replaced it.

One thing to know if you use the toolbar instead: publishing while a failure
mode is active keeps serving the previous version until one request succeeds
without that mode. The failure modes simulate a CMS the service cannot reach,
and a correction published during an outage can only propagate on the first
successful fetch. The `correction_propagated` log line shows exactly when that
happened.

### 4. Empty cache

The service never invents content. With nothing stored and a failing upstream
it returns 503. Warming makes this rare, so to see it, start the service before
the CMS:

```bash
# In terminal 1, stop npm run dev (Ctrl-C). Note that restarting the mock
# CMS resets every article to version 1.
# In terminal 2, restart the service; it logs cache_warming_skipped.
# Start npm run dev again, then:
curl -si "localhost:8000/articles/$ARTICLE?source=down" | grep -iE "^HTTP|^x-cache"
curl -si "localhost:8000/articles/$ARTICLE" | grep -iE "^HTTP|^x-cache"
curl -si "localhost:8000/articles/$ARTICLE?source=down" | grep -iE "^HTTP|^x-cache"
```

Expect `503` with `x-cache: miss`, then `200 fresh`, then `200 stale-error`.
One successful fetch is enough to make the article resilient again.

### 5. Unknown paths

```bash
curl -si "localhost:8000/articles/not/a/real/path" | grep -iE "^HTTP"
```

Expect 404. A 404 from the CMS is treated as an answer, not a failure, so it
is never served from cache (D-008).

## Observability

### /healthz

```bash
curl -s localhost:8000/healthz | python3 -m json.tool
```

```json
{
  "service": "ok",
  "upstream": {
    "state": "healthy",
    "recent_attempts": [{"outcome": "ok", "ms": 101.4}, "..."]
  },
  "cache": {"articles_cached": 4, "index_cached": true}
}
```

`state` is computed from the last ten upstream attempts: `healthy` if none
failed, `degraded` if some failed, `failing` if all failed (with at least
three), `unknown` before any attempt. Run the failure-mode loop and check
again to see it move to `degraded`; a few healthy requests bring it back.

### /metrics

```bash
curl -s localhost:8000/metrics | python3 -m json.tool
```

Counters are named `request.<cache result>` (one per served response, keyed by
the same value as the `x-cache` header), `upstream.<outcome>` (one per real
upstream attempt, after coalescing), and `corrections_propagated`. After the
walkthrough above you should see, for example, `request.fresh`,
`request.stale-timeout`, `request.stale-error`, `upstream.timeout`,
`upstream.http_error`, `upstream.invalid`, and `corrections_propagated: 1`.

### Log lines

The service writes one JSON object per line to the terminal it runs in. Three
event types answer the three questions in the README:

```
{"event": "upstream_fetch", "endpoint": "article", "outcome": "timeout", "ms": 1001.3, ...}
{"event": "request", "path": "/articles/...", "source": "hang", "cache": "stale-timeout", "status": 200, "version": "2", ...}
{"event": "correction_propagated", "path": "...", "old_version": 1, "new_version": 2, "ts": "..."}
```

`upstream_fetch` says whether the upstream is healthy right now. `request` says
whether a page was served from cache or fetched fresh. `correction_propagated`
says that a correction reached readers, and its `ts` says when.

## Extra: request coalescing

Each page view makes two identical requests to the service (one from
`generateMetadata`, one from the page render). Concurrent fetches for the same
article are collapsed into one CMS call:

```bash
for i in 1 2 3 4 5; do curl -s "localhost:8000/articles/$ARTICLE" -o /dev/null & done; wait
curl -s localhost:8000/metrics | python3 -c "import json,sys; c=json.load(sys.stdin)['counters']; print('requests fresh:', c.get('request.fresh'), ' upstream ok:', c.get('upstream.ok'))"
```

Compare the two numbers before and after: five requests, one upstream fetch.
The CMS terminal shows the same thing, one `GET /content/...` line for the
burst.

## Reading the decisions

`docs/DECISIONS.md` has one entry per non-obvious choice, in the order they
were made, each with the options considered and what was traded away. The
entries most worth reading first are D-002 (why revalidate on every request),
D-003 (why cache entries never expire), and D-013 and D-014 (what was
considered and not built, and why).
