"""Unit tests for the two cache-layer primitives."""

import asyncio

import pytest

from services.content_service.cache import ArticleCache, SingleFlight
from services.content_service.models import Article
from tests.conftest import ARTICLE


def _article(**overrides) -> Article:
    return Article.model_validate({**ARTICLE, **overrides})


class TestArticleCache:
    def test_entry_replaced_by_newer_fetch(self) -> None:
        cache = ArticleCache()
        cache.put_article(_article())
        cache.put_article(_article(version=2))
        entry = cache.get_article(ARTICLE["path"])
        assert entry is not None and entry.article.version == 2

    def test_miss_returns_none(self) -> None:
        assert ArticleCache().get_article("nope") is None


class TestSingleFlight:
    async def test_concurrent_callers_share_one_call(self) -> None:
        flights, calls = SingleFlight(), 0

        async def work() -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return "result"

        results = await asyncio.gather(*(flights.run("k", work) for _ in range(5)))
        assert calls == 1
        assert results == ["result"] * 5

    async def test_failure_is_shared_too(self) -> None:
        flights = SingleFlight()

        async def boom() -> None:
            await asyncio.sleep(0.01)
            raise RuntimeError("upstream sad")

        results = await asyncio.gather(
            *(flights.run("k", boom) for _ in range(3)), return_exceptions=True
        )
        assert all(isinstance(r, RuntimeError) for r in results)

    async def test_different_keys_do_not_coalesce(self) -> None:
        flights, calls = SingleFlight(), 0

        async def work() -> None:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)

        await asyncio.gather(flights.run("a", work), flights.run("b", work))
        assert calls == 2

    async def test_sequential_calls_fetch_fresh(self) -> None:
        # A finished flight must not be joined late. Revalidating on every
        # request depends on the next request starting a new fetch.
        flights, calls = SingleFlight(), 0

        async def work() -> None:
            nonlocal calls
            calls += 1

        await flights.run("k", work)
        await flights.run("k", work)
        assert calls == 2


@pytest.mark.parametrize("field", ["headline", "summary", "author"])
def test_validation_rejects_placeholders(field: str) -> None:
    with pytest.raises(ValueError):
        _article(**{field: "{{article.thing}}"})


def test_validation_rejects_null_version_and_dates() -> None:
    for bad in ({"version": None}, {"publishedAt": None}, {"version": 0}, {"body": []}):
        with pytest.raises(ValueError):
            _article(**bad)
