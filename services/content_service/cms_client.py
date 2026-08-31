"""HTTP client for the CMS.

All upstream I/O goes through this one class so that the timeout policy and
the error handling live in one place. This first version uses a generous
timeout on purpose: it should behave like a plain proxy so the failure modes
are visible before the cache handles them. The real time budget is decision
D-005 in docs/DECISIONS.md.
"""

import httpx

CMS_BASE_URL = "http://localhost:8001"

# Generous on purpose. Only `hang` will trip this. The real budget of
# about 1s is set later (D-005).
PHASE1_TIMEOUT_S = 10.0


class CmsClient:
    def __init__(self, base_url: str = CMS_BASE_URL) -> None:
        # One shared AsyncClient gives connection pooling and a single place to close.
        self._client = httpx.AsyncClient(base_url=base_url, timeout=PHASE1_TIMEOUT_S)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_index(self) -> httpx.Response:
        return await self._client.get("/content")

    async def fetch_article(self, path: str, source: str | None) -> httpx.Response:
        # `source` is forwarded unchanged so the failure modes work end to
        # end. It is test tooling and is never part of the article's
        # identity (AGENTS.md), which is why it appears only here.
        params = {"source": source} if source else None
        return await self._client.get(f"/content/{path}", params=params)
