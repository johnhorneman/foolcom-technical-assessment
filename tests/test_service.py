"""Behavior tests through the real app. Each test pins a property that was
first verified by hand in the browser. See conftest.py for the setup.
"""

import asyncio

import httpx

from services.content_service.main import _warm_cache, app
from tests.conftest import ARTICLE, FakeCms

PATH = ARTICLE["path"]
URL = f"/articles/{PATH}"


async def warm(client: httpx.AsyncClient) -> None:
    response = await client.get(URL)
    assert response.status_code == 200
    assert response.headers["x-cache"] == "fresh"


async def test_healthy_serves_fresh(client: httpx.AsyncClient) -> None:
    response = await client.get(URL)
    assert response.status_code == 200
    assert response.headers["x-cache"] == "fresh"
    assert response.headers["x-article-version"] == "1"
    assert response.json()["headline"] == ARTICLE["headline"]


async def test_cold_cache_failure_is_honest_503(client: httpx.AsyncClient) -> None:
    response = await client.get(URL, params={"source": "down"})
    assert response.status_code == 503
    assert response.headers["x-cache"] == "miss"


async def test_down_serves_stale(client: httpx.AsyncClient) -> None:
    await warm(client)
    response = await client.get(URL, params={"source": "down"})
    assert response.status_code == 200
    assert response.headers["x-cache"] == "stale-error"
    assert response.json()["body"] == ARTICLE["body"]


async def test_timeout_serves_stale(client: httpx.AsyncClient) -> None:
    await warm(client)
    response = await client.get(URL, params={"source": "hang"})
    assert response.status_code == 200
    assert response.headers["x-cache"] == "stale-timeout"


async def test_corrupt_never_poisons_cache(client: httpx.AsyncClient) -> None:
    await warm(client)
    corrupt = await client.get(URL, params={"source": "corrupt"})
    assert corrupt.status_code == 200
    assert corrupt.headers["x-cache"] == "stale-error"
    # The cached copy is still the real article, not the corrupt payload.
    assert corrupt.json()["headline"] == ARTICLE["headline"]
    after = await client.get(URL)
    assert after.headers["x-cache"] == "fresh"
    assert after.json()["version"] == 1


async def test_cache_key_ignores_source(client: httpx.AsyncClient) -> None:
    await warm(client)  # cached via a request with NO source param
    response = await client.get(URL, params={"source": "down"})
    # A source-mode request is served from the same path-keyed entry.
    assert response.status_code == 200
    assert response.json()["path"] == PATH


async def test_correction_propagates_and_survives_failures(
    client: httpx.AsyncClient, fake_cms: FakeCms
) -> None:
    await warm(client)
    fake_cms.publish_correction(PATH)
    corrected = await client.get(URL)
    assert corrected.headers["x-article-version"] == "2"
    assert corrected.headers["x-cache"] == "fresh"
    for source in ("down", "hang", "corrupt"):
        response = await client.get(URL, params={"source": source})
        assert response.status_code == 200
        assert response.headers["x-article-version"] == "2", source
    metrics = (await client.get("/metrics")).json()
    assert metrics["counters"]["corrections_propagated"] == 1


async def test_unknown_path_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/articles/not/a/real/path")
    assert response.status_code == 404


async def test_404_wins_over_cache(client: httpx.AsyncClient, fake_cms: FakeCms) -> None:
    # D-008: once the CMS says an article is gone, it is not served from cache.
    await warm(client)
    del fake_cms.store[PATH]
    response = await client.get(URL)
    assert response.status_code == 404


async def test_index_serves_stale_on_failure(client: httpx.AsyncClient, fake_cms: FakeCms) -> None:
    fresh = await client.get("/articles")
    assert fresh.headers["x-cache"] == "fresh"
    fake_cms.mode = "down"  # the index takes no source param; fail via mode
    stale = await client.get("/articles")
    assert stale.status_code == 200
    assert stale.headers["x-cache"] == "stale-error"
    assert stale.json() == fresh.json()


async def test_concurrent_requests_coalesce_upstream(
    client: httpx.AsyncClient, fake_cms: FakeCms
) -> None:
    responses = await asyncio.gather(*(client.get(URL) for _ in range(5)))
    assert all(r.status_code == 200 for r in responses)
    assert fake_cms.calls == 1


async def test_healthz_reports_upstream_state(client: httpx.AsyncClient, fake_cms: FakeCms) -> None:
    await warm(client)
    for _ in range(3):
        await client.get(URL, params={"source": "down"})
    health = (await client.get("/healthz")).json()
    assert health["upstream"]["state"] in ("degraded", "failing")
    assert health["cache"]["articles_cached"] == 1


async def test_warming_fills_cache(client: httpx.AsyncClient) -> None:
    await _warm_cache(app.state)
    assert app.state.cache.stats() == {"articles_cached": 1, "index_cached": True}


async def test_warming_tolerates_dead_upstream(
    client: httpx.AsyncClient, fake_cms: FakeCms
) -> None:
    fake_cms.mode = "down"
    await _warm_cache(app.state)  # must not raise; an empty cache is the fallback
    assert app.state.cache.stats()["articles_cached"] == 0


async def test_slow_response_still_updates_cache(
    client: httpx.AsyncClient, fake_cms: FakeCms
) -> None:
    # D-015: the reader gets the stored copy at the deadline, but the slow
    # fetch keeps running and writes the cache when it lands.
    await warm(client)
    fake_cms.publish_correction(PATH)
    response = await client.get(URL, params={"source": "slow"})
    assert response.status_code == 200
    assert response.headers["x-cache"] == "stale-timeout"
    assert response.headers["x-article-version"] == "1"
    await app.state.flights.drain()
    assert app.state.cache.get_article(PATH).article.version == 2
    metrics = (await client.get("/metrics")).json()
    assert metrics["counters"]["corrections_propagated"] == 1


async def test_cold_cache_slow_returns_503_then_warms(
    client: httpx.AsyncClient, fake_cms: FakeCms
) -> None:
    response = await client.get(URL, params={"source": "slow"})
    assert response.status_code == 503
    assert response.headers["x-cache"] == "miss"
    await app.state.flights.drain()
    assert app.state.cache.stats()["articles_cached"] == 1


async def test_healthz_reports_slow_upstream(client: httpx.AsyncClient, fake_cms: FakeCms) -> None:
    await client.get(URL, params={"source": "slow"})
    await app.state.flights.drain()
    health = (await client.get("/healthz")).json()
    assert health["upstream"]["state"] == "slow"
