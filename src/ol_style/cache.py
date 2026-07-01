"""File-hash based cache for StyleGuide profiles.

Caches StyleGuide results by content hash. Supports both in-memory
and disk-persisted modes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ol_style.schema import StyleGuide

logger = logging.getLogger(__name__)


class ProfileCache:
    """Content-hash based cache for StyleGuide objects.

    Use ``cache_dir=None`` for an in-memory only cache.
    Use ``cache_dir=Path(...)`` for disk-persisted cache that survives
    process restarts.
    """

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._memory: dict[str, dict] = {}
        if self._cache_dir is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash(self, content: str) -> str:
        """SHA256 hash of content, truncated to 16 chars for compact keys."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _disk_path(self, key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{key}.json"

    def get(self, content: str) -> "StyleGuide | None":
        """Get a cached StyleGuide by content. Returns None on miss."""
        from ol_style.schema import StyleGuide
        key = self._hash(content)
        # Check memory first
        if key in self._memory:
            return StyleGuide.from_dict(self._memory[key])
        # Check disk
        path = self._disk_path(key)
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Warm memory cache
                self._memory[key] = data
                return StyleGuide.from_dict(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read cache file %s: %s", path, e)
        return None

    def put(self, content: str, guide: "StyleGuide") -> None:
        """Cache a StyleGuide for the given content."""
        key = self._hash(content)
        data = guide.to_dict()
        self._memory[key] = data
        path = self._disk_path(key)
        if path is not None:
            try:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning("Failed to write cache file %s: %s", path, e)

    def clear(self) -> None:
        """Clear all cached entries (memory + disk)."""
        self._memory.clear()
        if self._cache_dir is not None:
            for path in self._cache_dir.glob("*.json"):
                try:
                    path.unlink()
                except OSError as e:
                    logger.warning("Failed to delete cache file %s: %s", path, e)

    @property
    def size(self) -> int:
        """Number of entries in the cache (memory view)."""
        return len(self._memory)
