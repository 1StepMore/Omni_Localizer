"""Omni-Localizer document style module.

Provides:
- StyleGuide dataclass — structured description of document writing style
- ProfileCache — content-hash based cache for StyleGuide results
- profile_document — LLM-based document profiling entry point
"""
from ol_style.schema import StyleGuide
from ol_style.cache import ProfileCache
from ol_style.doc_profiler import profile_document

__all__ = ["StyleGuide", "ProfileCache", "profile_document"]
__version__ = "0.2.0"
