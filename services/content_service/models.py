"""Article models. The contract is defined by types/article.ts.

These models are the defense against the `corrupt` failure mode (D-006). In
that mode the CMS returns HTTP 200 with JSON that has the right keys but
null values for version and dates and "{{template.placeholder}}" strings for
the text. A status code check and a key check would both pass, so every
payload has to pass strict typing and content checks before it can be
served or cached. The checks overlap on purpose: nulls fail the type check,
placeholders fail the content check, and the path comparison in cms_client
catches a valid article returned for the wrong URL.

Unknown fields are ignored rather than rejected. The CMS adding a field is a
contract change, not corruption.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _sane_text(value: str) -> str:
    """Reject strings that still contain unrendered CMS template placeholders."""
    if "{{" in value:
        raise ValueError("contains template placeholder")
    return value


class ArticleSummary(BaseModel):
    """Index entry: the subset of fields the home page needs."""

    path: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    author: str = Field(min_length=1)

    _no_placeholders = field_validator("path", "headline", "summary", "author")(_sane_text)


class Article(ArticleSummary):
    publishedAt: str
    updatedAt: str
    # strict=True also rejects booleans, since bool is a subclass of int.
    # Versions start at 1, so ge=1 rejects zero and negative values.
    version: int = Field(ge=1, strict=True)
    body: list[str] = Field(min_length=1)

    @field_validator("publishedAt", "updatedAt")
    @classmethod
    def _iso_datetime(cls, value: str) -> str:
        # Check that the value parses, but return the original string. The
        # frontend receives these fields as-is, and re-serializing could
        # change the format (Z versus +00:00).
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("body")
    @classmethod
    def _real_paragraphs(cls, paragraphs: list[str]) -> list[str]:
        for p in paragraphs:
            if not p.strip():
                raise ValueError("empty body paragraph")
            _sane_text(p)
        return paragraphs


class ArticleIndex(BaseModel):
    articles: list[ArticleSummary]
