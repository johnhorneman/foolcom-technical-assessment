"""Content service on port 8000. Sits between the Next.js app and the CMS.

Request flow (docs/DECISIONS.md D-002, D-003, D-005, D-015): start a fetch
from the CMS, or join one already in flight for the same article (D-009),
and wait for it up to the reader's deadline of about one second. If the
fetch finishes in time with a valid article, serve it. If it finishes with a
failure, serve the stored last-known-good copy. If it is still running at
the deadline, serve the stored copy and let the fetch finish in the
background; when it does, it updates the cache like any other successful
fetch. Return 503 only when there is no stored copy.

Every response carries X-Cache and X-Article-Version headers. Every request,
upstream attempt, and correction propagation is logged as a JSON line
(observability.py). /healthz and /metrics expose the same information for
operators.

The service revalidates on every request instead of using a TTL because
corrections are published directly to the CMS and this service is not
told about them. After a correction, every response has to be the corrected
version. When the CMS is healthy this costs about 100ms per request, which
is the CMS's own latency. When it is not, the reader's deadline bounds the
wait and the cache serves the response.

Run: uv run uvicorn services.content_service.main:app --port 8000 --reload
"""

import asyncio
import contextlib
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
from services.content_service.observability import Observability, log_event

# D-015: how long a reader waits for the CMS before getting the stored copy.
# About 10x the CMS's healthy latency (D-005). The fetch itself may keep
# running after this; see UPSTREAM_TIMEOUT in cms_client.py.
READER_DEADLINE_S = 1.0


async def _fetch_and_store_article(state, path: str, source: str | None) -> Article:
    """Fetch, validate, and store one article.

    This runs inside a flight, so it completes and writes the cache even if
    every reader stopped waiting at the deadline (D-015).
    """
    article = await state.cms.get_article(path, source)
    previous = state.cache.get_article(path)
    if previous is not None and article.version > previous.article.version:
        # A newer version has replaced the cached one. The timestamp on this
        # log line is when the correction reached readers.
        state.obs.record_propagation(path, previous.article.version, article.version)
    state.cache.put_article(article)
    return article


async def _fetch_and_store_index(state) -> ArticleIndex:
    index = await state.cms.get_index()
    state.cache.put_index(index)
    return index


async def _finished_within(task: asyncio.Task, deadline_s: float) -> bool:
    # asyncio.wait rather than wait_for: wait_for cancels the task when the
    # deadline passes, and the point of D-015 is that the fetch outlives the
    # reader's patience.
    done, _ = await asyncio.wait({task}, timeout=deadline_s)
    return task in done


async def _warm_cache(state) -> None:
    """Pre-fetch the index and every article at startup (D-012).

    Warming covers one case: the CMS is healthy when this service starts but
    fails before an article's first request. That case is common because
    this service is redeployed, which empties the cache, far more often than
    the CMS goes down. If warming fails, the service starts with an empty
    cache, which is how it behaved before warming existed. Warming must
    never prevent startup.

    Walking the whole catalog is only reasonable because it is four
    articles. In production the equivalent is a persistent or shared cache
    tier.
    """
    try:
        index = await state.cms.get_index()
    except UpstreamError as exc:
        log_event("cache_warming_skipped", reason=str(exc))
        return
    state.cache.put_index(index)
    warmed = 0
    for entry in index.articles:
        try:
            state.cache.put_article(await state.cms.get_article(entry.path, None))
            warmed += 1
        except UpstreamError:
            continue
    log_event("cache_warmed", articles=warmed, catalog=len(index.articles))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.obs = Observability(slow_ms=READER_DEADLINE_S * 1000)
    app.state.cms = CmsClient(obs=app.state.obs)
    app.state.cache = ArticleCache()
    app.state.flights = SingleFlight()
    app.state.deadline_s = READER_DEADLINE_S
    # Warm in the background. With a ten-second client timeout, a hung CMS
    # at startup would otherwise delay startup by most of a minute (D-012).
    warm_task = asyncio.create_task(_warm_cache(app.state))
    yield
    warm_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await warm_task
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
    # reader waits for.
    return "stale-timeout" if isinstance(exc, UpstreamTimeout) else "stale-error"


def _serve(payload: Article | ArticleIndex, cache_status: str) -> JSONResponse:
    headers = {"X-Cache": cache_status}
    if isinstance(payload, Article):
        headers["X-Article-Version"] = str(payload.version)
    return JSONResponse(payload.model_dump(), headers=headers)


def _unavailable(detail: str) -> JSONResponse:
    # Empty cache and no usable answer from the CMS. An error is better than
    # invented content, especially for financial articles (D-007).
    return JSONResponse(
        {"error": f"content temporarily unavailable ({detail})"},
        status_code=503,
        headers={"X-Cache": "miss"},
    )


DEADLINE_DETAIL = "no answer from upstream within the reader deadline"


@app.get("/articles")
async def article_index(request: Request) -> JSONResponse:
    state = request.app.state
    task = state.flights.start("index", lambda: _fetch_and_store_index(state))
    if await _finished_within(task, state.deadline_s):
        try:
            return _serve(task.result(), "fresh")
        except ArticleNotFound:
            raise
        except UpstreamError as exc:
            reason, detail = _stale_reason(exc), str(exc)
    else:
        reason, detail = "stale-timeout", DEADLINE_DETAIL
    cached = state.cache.get_index()
    if cached is not None:
        return _serve(cached.index, reason)
    return _unavailable(detail)


@app.get("/articles/{path:path}")
async def article(request: Request, path: str, source: str | None = None) -> JSONResponse:
    state = request.app.state

    # The flight key includes source because source changes what the CMS
    # does. The cache key is the path alone because source is not part of
    # the article's identity. See SingleFlight and D-009.
    key = f"article:{path}?source={source or ''}"
    task = state.flights.start(key, lambda: _fetch_and_store_article(state, path, source))

    if await _finished_within(task, state.deadline_s):
        try:
            return _serve(task.result(), "fresh")
        except ArticleNotFound:
            raise  # an answer, not a failure; handled by not_found() (D-008)
        except UpstreamError as exc:
            reason, detail = _stale_reason(exc), str(exc)
    else:
        # The fetch keeps running; if it succeeds it writes the cache (D-015).
        reason, detail = "stale-timeout", DEADLINE_DETAIL

    cached = state.cache.get_article(path)
    if cached is not None:
        # A real article, even an old one, is better than an error.
        return _serve(cached.article, reason)
    return _unavailable(detail)


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
