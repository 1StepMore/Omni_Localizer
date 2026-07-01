"""Omni-Localizer terminology management module.

Provides glossary loading, RAG-based injection, term extraction, and disambiguation.

The module exposes TWO glossary APIs:

* **Legacy (function-based)** — ``load_glossary`` and ``get_relevant_terms``
  in ``ol_terminology.glossary``. Returns ``dict[str, dict[str, Any]]``.
  Consumed by BatchProcessor and the legacy RAG path.
* **NEW v1 (dataclass-based, PR12)** — ``Glossary`` in
  ``ol_terminology.glossary_class`` plus the module-level ``load_glossary``
  re-export. Backed by the
  ``{terms: [{source, targets}, ...]}`` JSON/YAML schema; exposes
  ``find_relevant`` and ``inject_into_prompt``.

Both APIs are kept side-by-side to avoid breaking existing tests
(``test_glossary_loader.py`` covers the legacy one).
"""
from ol_terminology.glossary import load_glossary, get_relevant_terms
from ol_terminology.glossary_class import Glossary
from ol_terminology.rag_injector import build_translate_prompt
from ol_terminology.extractor import extract_terms
from ol_terminology.disambiguator import disambiguate
from ol_terminology.verifier import (
    TermVerificationEntry,
    InconsistencyEntry,
    TermVerificationReport,
    verify_translation,
)

__all__ = [
    "Glossary",          # NEW v1 dataclass-based API (PR12)
    "load_glossary",     # legacy function-based loader (returns dict)
    "get_relevant_terms",
    "build_translate_prompt",
    "extract_terms",
    "disambiguate",
    "TermVerificationEntry",
    "InconsistencyEntry",
    "TermVerificationReport",
    "verify_translation",
]
