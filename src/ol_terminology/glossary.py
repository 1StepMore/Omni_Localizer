"""Glossary loading and relevance-based term retrieval."""
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)


def load_glossary(path: Path) -> dict[str, dict[str, Any]]:
    """Load and parse a JSON glossary file.

    Args:
        path: Path to the JSON glossary file.

    Returns:
        Dictionary mapping terms to their metadata:
        {
            "term": {
                "translation": str,
                "variants": dict[str, str],
                "confidence": float
            }
        }

    Raises:
        FileNotFoundError: If glossary file does not exist.
        ValueError: If JSON is malformed.
    """
    if not path.exists():
        logger.warning(f"Glossary file not found: {path}, returning empty dict")
        return {}

    import json

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse glossary JSON at {path}: {e}")
        raise ValueError(f"Malformed glossary JSON: {e}") from e

    glossary: dict[str, dict[str, Any]] = {}

    for term, data in raw.items():
        if isinstance(data, dict):
            glossary[term] = {
                "translation": data.get("translation", ""),
                "variants": data.get("variants", {}),
                "confidence": data.get("confidence", 1.0),
            }
        else:
            glossary[term] = {
                "translation": str(data),
                "variants": {},
                "confidence": 1.0,
            }

    logger.info(f"Loaded {len(glossary)} terms from glossary: {path}")
    return glossary


def load_glossary_from_path(path: str | Path, config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load a JSON glossary file from a path, with optional config directory for relative paths.

    Args:
        path: Path to the JSON glossary file (str or Path).
        config_dir: Optional base directory for resolving relative paths.

    Returns:
        Dictionary mapping terms to their metadata (same format as load_glossary).

    Raises:
        FileNotFoundError: If glossary file does not exist.
        ValueError: If JSON is malformed.
    """
    import json

    path = Path(path)

    # Resolve relative paths: use config_dir if provided, otherwise CWD
    if not path.is_absolute():
        base_dir = config_dir if config_dir is not None else Path.cwd()
        path = base_dir / path

    if not path.exists():
        raise FileNotFoundError(f"Glossary file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed glossary JSON: {e}") from e

    glossary: dict[str, dict[str, Any]] = {}

    for term, data in raw.items():
        if isinstance(data, dict):
            glossary[term] = {
                "translation": data.get("translation", ""),
                "variants": data.get("variants", {}),
                "confidence": data.get("confidence", 1.0),
            }
        else:
            glossary[term] = {
                "translation": str(data),
                "variants": {},
                "confidence": 1.0,
            }

    logger.info(f"Loaded {len(glossary)} terms from glossary: {path}")
    return glossary


def get_relevant_terms(
    text: str,
    glossary: dict[str, dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Select top-k terms from glossary relevant to the given text.

    Selection is based on:
    - Exact substring matches in text
    - Case-insensitive matches
    - Confidence scores for ties

    Args:
        text: The source text to match against.
        top_k: Maximum number of terms to return.
        glossary: Dictionary of glossary terms.

    Returns:
        List of term dictionaries with term, translation, confidence.
        Returns up to top_k terms, sorted by relevance (exact match > partial > confidence).
    """
    if not text or not glossary:
        return []

    text_lower = text.lower()
    scored: list[tuple[float, dict[str, Any]]] = []

    for term, meta in glossary.items():
        score = 0.0

        if term in text:
            score = 3.0
        elif term.lower() in text_lower:
            score = 2.0
        else:
            for variant in meta.get("variants", {}).values():
                if variant and variant in text:
                    score = max(score, 1.5)
                    break

        if score > 0:
            score += meta.get("confidence", 1.0) * 0.1
            scored.append((score, {"term": term, **meta}))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [term for _, term in scored[:top_k]]

    return results