"""Omni-Localizer document style module.

Provides:
- StyleGuide dataclass — structured description of document writing style
- ProfileCache — content-hash based cache for StyleGuide results
"""
from ol_style.schema import StyleGuide
from ol_style.cache import ProfileCache

__all__ = ["StyleGuide", "ProfileCache"]
__version__ = "0.2.0"
