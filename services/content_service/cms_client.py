"""HTTP client for the CMS, plus the exception types that describe its failures.

All upstream I/O goes through this module so that the timeout policy and the
failure classification live in one place. Callers never see httpx or Pydantic
exceptions. Every failure is raised as one of the UpstreamError subclasses
below, which will let the cache layer treat a timeout, a 500, and an invalid
payload the same way: fall back to the last known good copy.

The timeout is still the generous first-version value. The real budget of
about 1s is decision D-005 and arrives with the cache.
"""

import httpx
from pydantic import ValidationError

from services.content_service.models import Article, ArticleIndex

CMS_BASE_URL = "http://localhost:8001"

# Generous on purpose until the cache exists to absorb timeouts (D-005).
PHASE1_TIMEOUT_S = 10.0


class UpstreamError(Exception):
    """Base class. The CMS failed in one of the ways classified below."""


class ArticleNotFound(UpstreamError):
    """The CMS returned 404. This is an answer, not a failure."""


class UpstreamTimeout(UpstreamError):
    """The CMS did not answer within the time budget (`slow` and `hang`)."""


class UpstreamUnreachable(UpstreamError):
    """Connection-level failure: refused, reset, or DNS."""


class UpstreamHTTPError(UpstreamError):
    """The CMS returned an unexpected non-2xx status (`down` returns 500)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"upstream returned HTTP {status_code}")
        self.status_code = status_code


class UpstreamInvalid(UpstreamError):
    """The CMS returned 200 but the body failed validation (`corrupt`)."""


class CmsClient:
    def __init__(self, base_url: str = CMS_BASE_URL) -> None:
        # One shared AsyncClient gives connection pooling and a single place to close.
        self._client = httpx.AsyncClient(base_url=base_url, timeout=PHASE1_TIMEOUT_S)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_index(self) -> ArticleIndex:
        payload = await self._get_json("/content", params=None)
        try:
            return ArticleIndex.model_validate(payload)
        except ValidationError as exc:
            raise UpstreamInvalid(f"invalid article index: {exc.errors()[:3]}") from exc

    async def get_article(self, path: str, source: str | None) -> Article:
        # `source` is forwarded unchanged so the failure modes work end to
        # end. It is test tooling and is never part of the article's
        # identity (AGENTS.md).
        params = {"source": source} if source else None
        payload = await self._get_json(f"/content/{path}", params=params)
        try:
            article = Article.model_validate(payload)
        except ValidationError as exc:
            raise UpstreamInvalid(f"invalid article: {exc.errors()[:3]}") from exc
        if article.path != path:
            # A valid article for a different path is still the wrong answer.
            raise UpstreamInvalid(f"path mismatch: asked {path!r}, got {article.path!r}")
        return article

    async def _get_json(self, url: str, params: dict | None) -> object:
        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnreachable(str(exc)) from exc

        if response.status_code == 404:
            raise ArticleNotFound(url)
        if response.status_code != 200:
            raise UpstreamHTTPError(response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamInvalid("response body is not JSON") from exc
