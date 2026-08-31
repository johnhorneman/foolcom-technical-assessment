"""Content service on port 8000. Sits between the Next.js app and the CMS.

Request flow (docs/DECISIONS.md D-002, D-003, D-005): fetch the article from
the CMS under a short time budget. If that succeeds, serve it and store it
as the last known good copy. If the fetch times out, errors, or returns
invalid content, serve the stored copy. Return 503 only when there is no
stored copy either. Concurrent fetches for the same article are coalesced
(D-009).

Every response carries X-Cache and X-Article-Version headers. Every request,
upstream attempt, and correction propagation is logged as a JSON line
(observability.py). /healthz and /metrics expose the same information for
operators.

The service revalidates on every request instead of using a TTL because
corrections are published directly to the CMS and this service is not
told about them. After a correction, every response has to be the corrected
version. When the CMS is healthy this costs about 100ms per request, which
is the CMS's own latency. When it is not, the time budget bounds the cost
and the cache serves the response.

Run: uv run uvicorn services.content_service.main:app --port 8000 --reload
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.content_service.cache import ArticleCache, SingleFlight
from services.content_service.cms_client import (
    ArticleNotFound,
    CmsClient,
    UpstreamError,
    UpstreamTimeout,
)
from services.content_service.models import Article, ArticleIndex
from services.content_service.observability import Observability


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.obs = Observability()
    app.state.cms = CmsClient(obs=app.state.obs)
    app.state.cache = ArticleCache()
    app.state.flights = SingleFlight()
    yield
    await app.state.cms.aclose()


app = FastAPI(title="content-service", lifespan=lifespan)


@app.middleware("http")
async def request_log(request: Request, call_next):
    # Log one `request` line per article or index request. Cache status and
    # version are read from the response headers, so this middleware does
    # not need to know anything about the routes.
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path == "/articles" or request.url.path.startswith("/articles/"):
        request.app.state.obs.record_request(
            path=request.url.path,
            source=request.query_params.get("source"),
            cache=response.headers.get("x-cache", "-"),
            status=response.status_code,
            ms=(time.perf_counter() - started) * 1000,
            version=response.headers.get("x-article-version"),
        )
    return response


@app.exception_handler(ArticleNotFound)
async def not_found(request: Request, exc: ArticleNotFound) -> JSONResponse:
    # D-008: a 404 is the CMS answering, not the CMS failing, so it does not
    # trigger the stale fallback. Serving a cached copy of an article the
    # CMS says is gone would keep unpublished content available indefinitely.
    return JSONResponse({"error": "Not Found"}, status_code=404)


def _stale_reason(exc: UpstreamError) -> str:
    # The header only needs two buckets; the exact error type goes to the
    # logs. Timeouts get their own bucket because they are the failures the
    # reader waits for: a stale-timeout response spent the whole budget.
    return "stale-timeout" if isinstance(exc, UpstreamTimeout) else "stale-error"


def _serve(payload: Article | ArticleIndex, cache_status: str) -> JSONResponse:
    headers = {"X-Cache": cache_status}
    if isinstance(payload, Article):
        headers["X-Article-Version"] = str(payload.version)
    return JSONResponse(payload.model_dump(), headers=headers)


def _unavailable(exc: UpstreamError) -> JSONResponse:
    # Empty cache and a failing upstream. An error is better than invented
    # content, especially for financial articles (D-007).
    return JSONResponse(
        {"error": f"content temporarily unavailable ({exc})"},
        status_code=503,
        headers={"X-Cache": "miss"},
    )


@app.get("/articles")
async def article_index(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        index = await state.flights.run("index", state.cms.get_index)
    except ArticleNotFound:
        raise
    except UpstreamError as exc:
        cached = state.cache.get_index()
        if cached is not None:
            return _serve(cached.index, _stale_reason(exc))
        return _unavailable(exc)
    state.cache.put_index(index)
    return _serve(index, "fresh")


@app.get("/articles/{path:path}")
async def article(request: Request, path: str, source: str | None = None) -> JSONResponse:
    state = request.app.state

    # The flight key includes source because source changes what the CMS
    # does. The cache key is the path alone because source is not part of
    # the article's identity. See SingleFlight and D-009.
    async def fetch() -> Article:
        return await state.cms.get_article(path, source)

    try:
        fresh = await state.flights.run(f"article:{path}?source={source or ''}", fetch)
    except ArticleNotFound:
        raise  # an answer, not a failure; handled by not_found() (D-008)
    except UpstreamError as exc:
        cached = state.cache.get_article(path)
        if cached is not None:
            # A real article, even an old one, is better than an error.
            return _serve(cached.article, _stale_reason(exc))
        return _unavailable(exc)

    previous = state.cache.get_article(path)
    if previous is not None and fresh.version > previous.article.version:
        # A newer version has replaced the cached one. The timestamp on this
        # log line is when the correction reached readers.
        state.obs.record_propagation(path, previous.article.version, fresh.version)
    state.cache.put_article(fresh)
    return _serve(fresh, "fresh")


@app.get("/healthz")
async def healthz(request: Request) -> dict:
    state = request.app.state
    return {
        "service": "ok",
        "upstream": state.obs.upstream_state(),
        "cache": state.cache.stats(),
    }


@app.get("/metrics")
async def metrics(request: Request) -> dict:
    return request.app.state.obs.metrics_snapshot()
