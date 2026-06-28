"""A12.2: Glossary dataclass — load, validate, find relevant, inject into prompt.

This module is the NEW (PR12) glossary API. It coexists with the legacy
function-based API in ``ol_terminology.glossary`` (the one that returns
``dict[str, dict[str, Any]]``) — the legacy module is untouched so
``test_glossary_loader.py`` keeps passing.

Glossary JSON/YAML format (v1, this PR):

    {
      "terms": [
        {"source": "API", "targets": ["应用程序接口", "API"]},
        {"source": "rendering", "targets": ["渲染"]}
      ]
    }

The dataclass stores ``terms`` as ``dict[str, list[str]]``. Relevance
ranking is a deterministic substring-match count: top-N with the highest
occurrence count, ties broken by source string order.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ol_terminology.schema import validate_glossary_payload


@dataclass
class Glossary:
    """In-memory glossary with source→target(s) mappings.

    Use :meth:`load` to construct from a JSON or YAML file. Use
    :meth:`find_relevant` to get the top-N terms that match a source
    text. Use :meth:`inject_into_prompt` to build a translation prompt
    that includes those matched terms.

    ``target_lang`` is an optional metadata field extracted from the
    glossary file's top-level ``target_lang`` key. When set, it records
    the intended target language for this glossary. Use :meth:`for_target`
    to validate that the glossary matches a requested target language.
    """

    terms: dict[str, list[str]] = field(default_factory=dict)
    target_lang: str | None = None

    # ---------------------------------------------------------------- load

    @staticmethod
    def load(path: Path | str) -> "Glossary":
        """Load and validate a glossary file (JSON or YAML).

        Args:
            path: Path to a ``.json`` or ``.yaml`` / ``.yml`` file.

        Returns:
            A :class:`Glossary` instance.

        Raises:
            FileNotFoundError: if ``path`` does not exist.
            ValueError: if the file is malformed (syntax or schema error).
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Glossary file not found: {p}")

        suffix = p.suffix.lower()
        if suffix in (".yaml", ".yml"):
            payload = _read_yaml(p)
        else:
            # Default to JSON for ``.json`` and unknown extensions — matches
            # the spec ("reads JSON or YAML"; JSON is the more common form).
            payload = _read_json(p)

        validated = validate_glossary_payload(payload)
        # ``model_dump()`` gives us a dict-shaped payload with the validated
        # terms; we re-shape into the dataclass's flat ``{source: [targets]}``
        # dict for fast lookup.
        dump = validated.model_dump()
        return Glossary(
            terms={entry["source"]: list(entry["targets"]) for entry in dump["terms"]},
            target_lang=dump.get("target_lang"),
        )

    # ---------------------------------------------------------- find_relevant

    def find_relevant(
        self, source_text: str, max_terms: int = 5,
    ) -> list[tuple[str, list[str]]]:
        """Return the top-N most relevant terms for ``source_text``.

        Relevance is a deterministic substring-match count: for each
        term we count how many non-overlapping occurrences of the term
        appear in ``source_text`` (case-sensitive — the user picks the
        case they want to match in their glossary), and return the
        ``max_terms`` terms with the highest count, ordered by count
        descending. Terms with count == 0 are excluded.

        Ties are broken by source-string order (insertion order) for
        determinism — there is no randomness.

        Args:
            source_text: The text we want to translate.
            max_terms:   Maximum number of terms to return (default 5).

        Returns:
            A list of ``(source, targets)`` tuples, length ``<= max_terms``.
        """
        if not self.terms or not source_text:
            return []

        # Score every term that has at least one occurrence.
        scored: list[tuple[int, str, list[str]]] = []
        for src, tgts in self.terms.items():
            count = source_text.count(src)
            if count > 0:
                scored.append((count, src, tgts))

        # Sort by count desc. Python's sort is stable, so ties preserve
        # insertion order of self.terms — which is the deterministic
        # tie-breaker the spec calls for.
        scored.sort(key=lambda item: item[0], reverse=True)

        return [(src, tgts) for _, src, tgts in scored[:max_terms]]

    # -------------------------------------------------------------- for_target

    def for_target(self, target_lang: str) -> "Glossary":
        """Validate that this glossary's target_lang matches the requested language.

        If the glossary has no ``target_lang`` metadata (loaded from a file
        without the field), the check is skipped and the glossary is returned
        as-is — the user may be using a multi-target glossary.

        Args:
            target_lang: The requested target language code.

        Returns:
            ``self`` if validation passes.

        Raises:
            ValueError: if ``target_lang`` is set on the glossary and does not
                match the requested language.
        """
        if self.target_lang is not None and self.target_lang != target_lang:
            raise ValueError(
                f"Glossary target_lang mismatch: glossary is for '{self.target_lang}', "
                f"but translation targets '{target_lang}'"
            )
        return self

    # ---------------------------------------------------- inject_into_prompt

    def inject_into_prompt(
        self, source_text: str, prompt: str, max_terms: int = 5,
    ) -> str:
        """Append matched glossary terms to ``prompt`` and return the result.

        If no terms match, the prompt is returned unchanged. Otherwise the
        matched terms are appended as a single line in the format
        ``Use these terms: src→tgt, src2→tgt2, ...`` (per the spec in
        slim-pipeline-hardening.md §A12).

        Args:
            source_text: The text being translated (used to find relevant terms).
            prompt:      The base translation prompt to augment.
            max_terms:   How many top terms to inject (default 5).

        Returns:
            ``prompt`` with a ``Use these terms: ...`` line appended.
        """
        matched = self.find_relevant(source_text, max_terms=max_terms)
        if not matched:
            return prompt

        # Format: "src→tgt" (using the FIRST target if multiple; this keeps
        # the injected line compact — the LLM only needs one suggestion to
        # bias its translation).
        term_strs: list[str] = []
        for src, tgts in matched:
            primary = tgts[0] if tgts else ""
            term_strs.append(f"{src}→{primary}" if primary else src)

        # H1-H3: Sanitize glossary terms against prompt injection — strip
        # characters that could break out of the data context.
        _safe_terms = [
            t.replace("\n", " ").replace("\r", " ")
            for t in term_strs
        ]
        return (
            f"{prompt}\n\n"
            f"Use these terms: {', '.join(_safe_terms)}"
        )


# --------------------------------------------------------------------- helpers


def _read_json(path: Path) -> Any:
    """Read a JSON file, raising ``ValueError`` on parse error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path}: {exc}") from exc


def _read_yaml(path: Path) -> Any:
    """Read a YAML file, raising ``ValueError`` on parse error or missing dep.

    PyYAML is in the project's required dependencies (pyproject.toml:
    ``PyYAML>=6.0.0``) so the import should always succeed in production;
    the ``ImportError`` branch is a defense-in-depth for stripped-down envs.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(
            f"Cannot read YAML glossary {path}: PyYAML is not installed"
        ) from exc
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in {path}: {exc}") from exc
