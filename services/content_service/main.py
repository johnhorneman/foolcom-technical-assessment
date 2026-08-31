"""Content service on port 8000. Sits between the Next.js app and the CMS.

Request flow (docs/DECISIONS.md D-002, D-003, D-005): fetch the article from
the CMS under a short time budget. If that succeeds, serve it and store it
as the last known good copy. If the fetch times out, errors, or returns
invalid content, serve the stored copy. Return 503 only when there is no
stored copy either.

The service revalidates on every request instead of using a TTL because
corrections are published directly to the CMS and this service is not
told about them. After a correction, every response has to be the corrected
version. When the CMS is healthy this costs about 100ms per request, which
is the CMS's own latency. When it is not, the time budget bounds the cost
and the cache serves the response.

Run: uv run uvicorn services.content_service.main:app --port 8000 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.content_service.cache import ArticleCache
from services.content_service.cms_client import (
    ArticleNotFound,
    CmsClient,
    UpstreamError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cms = CmsClient()
    app.state.cache = ArticleCache()
    yield
    await app.state.cms.aclose()


app = FastAPI(title="content-service", lifespan=lifespan)


@app.exception_handler(ArticleNotFound)
async def not_found(request: Request, exc: ArticleNotFound) -> JSONResponse:
    # D-008: a 404 is the CMS answering, not the CMS failing, so it does not
    # trigger the stale fallback. Serving a cached copy of an article the
    # CMS says is gone would keep unpublished content available indefinitely.
    return JSONResponse({"error": "Not Found"}, status_code=404)


def _unavailable(exc: UpstreamError) -> JSONResponse:
    # Empty cache and a failing upstream. An error is better than invented
    # content, especially for financial articles (D-007).
    return JSONResponse(
        {"error": f"content temporarily unavailable ({exc})"}, status_code=503
    )


@app.get("/articles")
async def article_index(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        index = await state.cms.get_index()
    except ArticleNotFound:
        raise
    except UpstreamError as exc:
        cached = state.cache.get_index()
        if cached is not None:
            return JSONResponse(cached.index.model_dump())
        return _unavailable(exc)
    state.cache.put_index(index)
    return JSONResponse(index.model_dump())


@app.get("/articles/{path:path}")
async def article(request: Request, path: str, source: str | None = None) -> JSONResponse:
    state = request.app.state
    try:
        fresh = await state.cms.get_article(path, source)
    except ArticleNotFound:
        raise  # an answer, not a failure; handled by not_found() (D-008)
    except UpstreamError as exc:
        cached = state.cache.get_article(path)
        if cached is not None:
            # A real article, even an old one, is better than an error.
            return JSONResponse(cached.article.model_dump())
        return _unavailable(exc)
    state.cache.put_article(fresh)
    return JSONResponse(fresh.model_dump())
