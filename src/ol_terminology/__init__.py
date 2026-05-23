"""Omni-Localizer terminology management module.

Provides glossary loading, RAG-based injection, term extraction, and disambiguation.
"""
from ol_terminology.glossary import load_glossary, get_relevant_terms
from ol_terminology.rag_injector import build_translate_prompt
from ol_terminology.extractor import extract_terms
from ol_terminology.disambiguator import disambiguate

__all__ = [
    "load_glossary",
    "get_relevant_terms",
    "build_translate_prompt",
    "extract_terms",
    "disambiguate",
]