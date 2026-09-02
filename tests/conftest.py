"""Shared test setup: a fake CMS at the httpx transport layer (D-011).

FakeCms mirrors the mock CMS's contract: the same failure modes, the same
corrupt payload, and the same correction behavior. It runs inside
httpx.MockTransport, so tests never touch the network, and it simulates
timeouts by raising httpx.ReadTimeout instead of waiting out a real budget.
The app under test is the real FastAPI app with its real client, cache, and
coalescer. Only the transport is fake. httpx's ASGITransport does not run
the lifespan, so the fixture does that wiring itself.
"""

import asyncio
import copy

import httpx
import pytest

from services.content_service.cache import ArticleCache, SingleFlight
from services.content_service.cms_client import CmsClient
from services.content_service.main import app
from services.content_service.observability import Observability

ARTICLE = {
    "path": "investing/2026/07/23/test-article",
    "headline": "Test Article Headline",
    "summary": "A perfectly ordinary summary.",
    "author": "Jane Fool",
    "publishedAt": "2026-07-23T04:54:00.000Z",
    "updatedAt": "2026-07-23T04:54:00.000Z",
    "version": 1,
    "body": ["First paragraph.", "Second paragraph."],
}

# Copied from the mock CMS: valid structure, unusable content.
CORRUPT_PAYLOAD = {
    "path": "{{article.path}}",
    "headline": "{{article.headline}}",
    "summary": "{{article.summary}}",
    "author": "{{byline.display_name}}",
    "publishedAt": None,
    "updatedAt": None,
    "version": None,
    "body": ["{{article.body.blocks}}"],
}

INDEX_KEYS = ("path", "headline", "summary", "author")


class FakeCms:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {ARTICLE["path"]: copy.deepcopy(ARTICLE)}
        self.mode = "healthy"  # applies when the request carries no ?source=
        self.calls = 0
        self.slow_s = 0.3  # `slow` mode sleeps this long, then answers normally

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        # Sleep long enough that concurrent requests overlap, which the
        # coalescing test depends on, but short enough to keep the suite
        # fast. Apart from `slow`, the failure modes return immediately.
        await asyncio.sleep(0.02)
        mode = request.url.params.get("source") or self.mode
        if mode == "down":
            return httpx.Response(500, json={"error": "Internal Server Error"})
        if mode == "hang":
            # Stands in for the client timeout expiring: no answer, ever.
            raise httpx.ReadTimeout("simulated client timeout", request=request)
        if mode == "slow":
            # Answers correctly, but after the reader's deadline (D-015).
            await asyncio.sleep(self.slow_s)
        if mode == "corrupt":
            return httpx.Response(200, json=CORRUPT_PAYLOAD)
        if request.url.path == "/content":
            index = [{k: a[k] for k in INDEX_KEYS} for a in self.store.values()]
            return httpx.Response(200, json={"articles": index})
        path = request.url.path.removeprefix("/content/")
        found = self.store.get(path)
        if found is None:
            return httpx.Response(404, json={"error": "Not Found"})
        return httpx.Response(200, json=found)

    def publish_correction(self, path: str) -> None:
        article = self.store[path]
        article["version"] += 1
        article["updatedAt"] = "2026-07-24T00:00:00.000Z"
        article["body"] = [f"Correction (v{article['version']}): updated.", *article["body"]]


@pytest.fixture
async def fake_cms() -> FakeCms:
    return FakeCms()


@pytest.fixture
async def client(fake_cms: FakeCms):
    # ASGITransport does not run lifespan, so wire app.state the same way.
    app.state.obs = Observability(slow_ms=100)
    app.state.cms = CmsClient(obs=app.state.obs, transport=httpx.MockTransport(fake_cms.handler))
    app.state.cache = ArticleCache()
    app.state.flights = SingleFlight()
    # Short deadline so the slow path is exercised in real time without
    # slowing the suite: healthy answers in ~20ms, slow in ~300ms.
    app.state.deadline_s = 0.1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client
        await app.state.flights.drain()  # let background fetches settle
    await app.state.cms.aclose()
