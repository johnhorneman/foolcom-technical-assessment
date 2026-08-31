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
between awaits and no lock is needed for memory safety here. Coalescing of
duplicate upstream fetches is a separate concern and is added in a later
commit.
"""

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

    def put_index(self, index: ArticleIndex) -> None:
        self._index = IndexEntry(index=index, fetched_at=_now())
