"""Pydantic schema for the v1 glossary JSON/YAML format (PR12, A12.2).

Glossary file format (v1):

    {
      "terms": [
        {"source": "API", "targets": ["应用程序接口", "API"]},
        {"source": "rendering", "targets": ["渲染"]},
        ...
      ]
    }

The Pydantic model is the single source of truth for "what shape is valid
glossary data". Both ``Glossary.load`` (JSON) and ``Glossary.load`` (YAML)
funnel into the same validator. On schema violation we raise ``ValueError``
(test contract) — the underlying ``pydantic.ValidationError`` is unwrapped
so callers see a single, predictable error type.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class _TermEntry(BaseModel):
    """One source→targets entry inside the ``terms`` array."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Source-language term")
    targets: List[str] = Field(..., min_length=1, description="One or more target-language equivalents")

    @field_validator("targets")
    @classmethod
    def _no_empty_targets(cls, v: List[str]) -> List[str]:
        if any(not t.strip() for t in v):
            raise ValueError("targets entries must be non-empty strings")
        return v


class _GlossaryFile(BaseModel):
    """Top-level shape of a glossary file."""

    model_config = ConfigDict(extra="forbid")

    target_lang: str | None = Field(default=None, description="Optional target language code for this glossary")
    terms: List[_TermEntry] = Field(..., min_length=0)


def validate_glossary_payload(payload: dict | list) -> _GlossaryFile:
    """Validate a parsed JSON/YAML payload. Raises ``ValueError`` on failure.

    The function unwraps ``pydantic.ValidationError`` into a plain
    ``ValueError`` so the test contract is uniform: callers don't need
    to know about Pydantic internals.
    """
    try:
        return _GlossaryFile.model_validate(payload)
    except ValidationError as exc:
        # Concatenate the first error message — Pydantic's `.errors()` list
        # is too noisy for an end user.
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "invalid glossary")
        raise ValueError(f"Glossary validation failed at {loc}: {msg}") from exc
