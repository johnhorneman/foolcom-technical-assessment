"""Mock upstream CMS.

This simulates a CMS API. It is part of the exercise
harness: DO NOT MODIFY this package. Treat it like a remote service you
don't own.

Failure modes are selected per-request via `?source=<mode>`:
    (none)/healthy  responds normally (~100ms)
    slow            responds successfully, after several seconds
    down            returns 500 errors
    hang            never responds
    corrupt         returns structurally-valid JSON that isn't a real article
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

HEALTHY_LATENCY_S = 0.1
SLOW_LATENCY_S = 8.0

_seed_articles = json.loads((Path(__file__).parent / "seed_articles.json").read_text())

_store: dict[str, dict] = {a["path"]: dict(a) for a in _seed_articles}

CORRUPT_ARTICLE_PAYLOAD = {
    "path": "{{article.path}}",
    "headline": "{{article.headline}}",
    "summary": "{{article.summary}}",
    "author": "{{byline.display_name}}",
    "publishedAt": None,
    "updatedAt": None,
    "version": None,
    "body": ["{{article.body.blocks}}"],
}

app = FastAPI(title="upstream-cms (mock)")


@app.get("/content")
async def article_index() -> dict:
    await asyncio.sleep(HEALTHY_LATENCY_S)
    return {
        "articles": [
            {key: article[key] for key in ("path", "headline", "summary", "author")}
            for article in _store.values()
        ]
    }


@app.get("/content/{path:path}")
async def article_content(path: str, source: str = "healthy") -> JSONResponse:
    if source == "slow":
        await asyncio.sleep(SLOW_LATENCY_S)
    elif source == "down":
        await asyncio.sleep(HEALTHY_LATENCY_S)
        return JSONResponse({"error": "Internal Server Error"}, status_code=500)
    elif source == "hang":
        await asyncio.Event().wait()  # never set: this request never responds
    elif source == "corrupt":
        await asyncio.sleep(HEALTHY_LATENCY_S)
        return JSONResponse(CORRUPT_ARTICLE_PAYLOAD)
    else:
        await asyncio.sleep(HEALTHY_LATENCY_S)

    found = _store.get(path)
    if found is None:
        return JSONResponse({"error": "Not Found"}, status_code=404)
    return JSONResponse(found)


@app.post("/admin")
async def publish_correction(request: Request) -> JSONResponse:
    """Simulates an editor publishing a correction: bumps version and updatedAt."""
    path = request.query_params.get("publish-correction")

    if not path:
        return JSONResponse(
            {"error": "Missing publish-correction=<article path> query param"},
            status_code=400,
        )

    article = _store.get(path)
    if article is None:
        return JSONResponse({"error": f"No article at path: {path}"}, status_code=404)

    version = article["version"] + 1
    corrected = {
        **article,
        "version": version,
        "updatedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "body": [
            f"Correction (v{version}): This article has been updated by our editorial team.",
            *[p for p in article["body"] if not p.startswith("Correction (v")],
        ],
    }
    _store[path] = corrected

    return JSONResponse(
        {
            "published": corrected["path"],
            "version": corrected["version"],
            "updatedAt": corrected["updatedAt"],
        }
    )
