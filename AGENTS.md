# AGENTS.md

## What this project is

Technical assessment for Fool.com. A Next.js app (port 3000) renders articles fetched
from a Python content service (port 8000, ours — `services/content_service/`) which
fetches from a mock CMS (port 8001, NOT ours — `services/mock_cms/`).

The goal: article pages stay fast and serve accurate content under upstream failure
modes (`slow`, `down`, `hang`, `corrupt`) and always reflect published corrections.
Full requirements: `README.md`. Design rationale: `docs/DECISIONS.md`.

## Hard constraints — never violate

- NEVER modify anything under `services/mock_cms/`. Treat it as a remote service.
- The content service listens on port 8000 and must serve exactly:
  `GET /articles` and `GET /articles/<path>`, matching `types/article.ts`.
- `?source=` is test tooling: forward it to the CMS, but NEVER include it in a cache
  key or article identity.
- Only validated article payloads may be written to the cache. A corrupt payload in
  the cache is the worst possible bug in this project.
- No real infrastructure (no Redis server, no Docker, no external services).
- Keep dependencies minimal. Adding any dependency requires a decision-log entry.

## Commands

- `npm run dev` — starts Next.js (3000) + mock CMS (8001)
- `uv run uvicorn services.content_service.main:app --port 8000 --reload` — our service
- `uv run pytest` — tests (pytest-asyncio in auto mode)
- `uv run ruff check . && uv run ruff format --check .` — lint/format (line length 100)
- `npm run lint` — frontend lint (frontend should not need changes)

## Architecture (the short version agents need)

Per request: start or join a fetch from the CMS (`cache.py` SingleFlight, keyed by
path and source), wait up to the reader's deadline (~1s), validate with Pydantic
(`models.py`), store validated payloads as last-known-good (`cache.py`, keyed by path
only), serve the cached copy when the fetch fails or is still running at the deadline.
A fetch that outlives the reader keeps running (client timeout ~10s) and updates the
cache when it finishes. Cold cache + failing upstream → clean 503. Structured JSON logs + `/metrics` + `/healthz`
(`observability.py`).

## Working conventions — required

- Work in small, single-concern steps. One phase (see the plan) at a time; stop and
  wait for the human between phases.
- Every non-obvious choice gets an entry in `docs/DECISIONS.md` (template at top of
  that file) BEFORE or WITH the commit that implements it.
- Commit messages: conventional-commit subject; body contains `Why:` and, when
  applicable, `Decision: D-0xx`. No bundled unrelated changes.
- Comments in code explain WHY (budgets, key policy, non-expiry), not what.
- After any change to request flow, run the failure-mode checklist:
  every seeded article × {healthy, slow, down, hang, corrupt} responds fast with real
  content; publish a correction; repeat; every response shows the bumped version.
- Never mark work done if tests fail or the checklist doesn't pass.

## Verification quick reference

- Article page: `curl -s "localhost:8000/articles/<path>?source=<mode>"`
- Correction: `curl -X POST "localhost:3000/api/cms/admin?publish-correction=<path>"`
- CMS docs: `localhost:8001/docs`. CMS resets on restart (in-memory).
- Version badge in UI: `data-testid="article-version"`.
