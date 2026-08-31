"""Content service on port 8000. Sits between the Next.js app and the CMS.

This first version is a pass-through proxy. There is no cache and no
validation yet, so the CMS's failure modes reach the page unchanged. The
cache and validation are added in later commits (docs/DECISIONS.md D-002,
D-006).

Run: uv run uvicorn services.content_service.main:app --port 8000 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.content_service.cms_client import CmsClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cms = CmsClient()
    yield
    await app.state.cms.aclose()


app = FastAPI(title="content-service", lifespan=lifespan)


@app.get("/articles")
async def article_index(request: Request) -> JSONResponse:
    upstream = await request.app.state.cms.fetch_index()
    # Pass the body and status through unchanged. At this stage the service
    # only adds routing.
    return JSONResponse(upstream.json(), status_code=upstream.status_code)


@app.get("/articles/{path:path}")
async def article(request: Request, path: str, source: str | None = None) -> JSONResponse:
    upstream = await request.app.state.cms.fetch_article(path, source)
    return JSONResponse(upstream.json(), status_code=upstream.status_code)
