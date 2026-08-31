"""Content service on port 8000. Sits between the Next.js app and the CMS.

Every upstream response is validated before it is served, and every upstream
failure becomes a classified JSON error instead of a crash or a passed-through
payload. Pages still fail under the failure modes. The last-known-good cache
that handles those is the next commit (D-002, D-003).

Run: uv run uvicorn services.content_service.main:app --port 8000 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.content_service.cms_client import (
    ArticleNotFound,
    CmsClient,
    UpstreamError,
    UpstreamTimeout,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cms = CmsClient()
    yield
    await app.state.cms.aclose()


app = FastAPI(title="content-service", lifespan=lifespan)


# From here on the service always answers, and always with JSON. A 404 is a
# real answer. 502 and 504 report an upstream failure; the cache in the next
# commit will replace most of those with cached content.
@app.exception_handler(ArticleNotFound)
async def not_found(request: Request, exc: ArticleNotFound) -> JSONResponse:
    return JSONResponse({"error": "Not Found"}, status_code=404)


@app.exception_handler(UpstreamTimeout)
async def upstream_timeout(request: Request, exc: UpstreamTimeout) -> JSONResponse:
    return JSONResponse({"error": "upstream timed out"}, status_code=504)


@app.exception_handler(UpstreamError)
async def upstream_failed(request: Request, exc: UpstreamError) -> JSONResponse:
    return JSONResponse({"error": f"upstream failure: {exc}"}, status_code=502)


@app.get("/articles")
async def article_index(request: Request) -> JSONResponse:
    index = await request.app.state.cms.get_index()
    return JSONResponse(index.model_dump())


@app.get("/articles/{path:path}")
async def article(request: Request, path: str, source: str | None = None) -> JSONResponse:
    validated = await request.app.state.cms.get_article(path, source)
    return JSONResponse(validated.model_dump())
