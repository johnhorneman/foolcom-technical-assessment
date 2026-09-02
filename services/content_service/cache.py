"""Last-known-good article cache (docs/DECISIONS.md D-002, D-003).

This is a resilience cache, not a load-shedding cache. Freshness comes from
revalidating with the CMS on every request. This store exists so that when
the CMS is slow, down, hanging, or returning bad data, the service can serve
the newest copy that passed validation instead of an error.

Properties of the design:

- The key is the article path only. `?source=` is test tooling and not part
  of an article's identity (AGENTS.md). Keying by failure mode would let a
  bad variant shadow the real article.
- Only validated Article models are stored. The caller validates before
  calling put, so a corrupt payload cannot enter the store.
- Entries never expire. They are only replaced by a newer validated fetch.
  An entry that expired during a long outage would leave nothing to serve
  at the moment the cache matters most.
- Memory is bounded by the size of the catalog, four articles here. A
  production version would need an LRU bound and a shared tier (D-004).

Everything runs on one asyncio event loop, so dict mutations are atomic
between awaits and no lock is needed for memory safety. SingleFlight exists
for a different reason: to avoid duplicate upstream fetches when concurrent
requests want the same thing. Every page view already makes two identical
requests, one from generateMetadata and one from the page render.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime

from services.content_service.models import Article, ArticleIndex


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ArticleEntry:
    article: Article
    fetched_at: datetime


@dataclass
class IndexEntry:
    index: ArticleIndex
    fetched_at: datetime


class ArticleCache:
    def __init__(self) -> None:
        self._articles: dict[str, ArticleEntry] = {}
        self._index: IndexEntry | None = None

    def get_article(self, path: str) -> ArticleEntry | None:
        return self._articles.get(path)

    def put_article(self, article: Article) -> None:
        self._articles[article.path] = ArticleEntry(article=article, fetched_at=_now())

    def get_index(self) -> IndexEntry | None:
        return self._index

    def stats(self) -> dict:
        return {"articles_cached": len(self._articles), "index_cached": self._index is not None}

    def put_index(self, index: ArticleIndex) -> None:
        self._index = IndexEntry(index=index, fetched_at=_now())


class SingleFlight:
    """Coalesce concurrent calls for the same key into one in-flight task.

    The first caller for a key starts the work. Anyone who arrives while it
    is in flight gets the same task and shares its result, including a
    failure. Sharing failures is intentional: when the upstream is timing
    out, one caller should pay the wait, not every caller.

    The key matters (D-009). Flights are keyed by path and source, which
    together identify the fetch. The cache is keyed by path alone, which
    identifies the article. Coalescing by path alone could hand a healthy
    request the failure of a concurrent corrupt-mode fetch.

    Callers may stop waiting before the task finishes; main.py does exactly
    that at the reader's deadline (D-015). The task keeps running, and
    because the fetch writes the cache itself, its result still lands. The
    task is removed from the registry when it settles, so a finished flight
    is never joined late and the next request starts a new fetch, which is
    what revalidating on every request requires.
    """

    def __init__(self) -> None:
        self._flights: dict[str, asyncio.Task] = {}

    def start(self, key: str, fn: Callable[[], Coroutine]) -> asyncio.Task:
        """Return the in-flight task for `key`, starting one if none exists."""
        task = self._flights.get(key)
        if task is None:
            task = asyncio.create_task(fn())
            self._flights[key] = task
            task.add_done_callback(lambda done, key=key: self._settle(key, done))
        return task

    def _settle(self, key: str, task: asyncio.Task) -> None:
        if self._flights.get(key) is task:
            del self._flights[key]
        # A caller that stopped waiting never reads the result. Retrieve the
        # exception here so asyncio does not log it as never retrieved.
        if not task.cancelled():
            task.exception()

    async def run(self, key: str, fn: Callable[[], Coroutine]) -> object:
        """Start (or join) the flight for `key` and wait for its result."""
        return await self.start(key, fn)

    async def drain(self) -> None:
        """Wait for every in-flight task to settle. Used by tests."""
        await asyncio.gather(*list(self._flights.values()), return_exceptions=True)
