"""Content-addressed cache for OL CLI.

Re-runs of the same input+config skip the expensive translation and just
copy the cached <input_stem>.<ext> to the output dir. The cache root can
be overridden with the OMNI_CACHE_DIR env var (used by tests). Mode 0o700
protects any sensitive content (e.g., a translated MD file that contains
private info).
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

# CACHE_DIR_NAME is the per-module subdirectory under OMNI_CACHE_DIR.
CACHE_DIR_NAME = "ol"
_cache_logger = logging.getLogger("cli.cache")
_glossary_logger = logging.getLogger("cli.glossary")


def _cache_root() -> Path:
    """Return the OL cache root, creating it (mode 0o700) on first access.

    The env var is read at call-time (not at import-time) so tests can
    override it via monkeypatch.setenv() before any call.
    """
    root = Path(
        os.environ.get("OMNI_CACHE_DIR", str(Path.home() / ".omni_cache"))
    ) / CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _cache_key(
    input_path: Path,
    config_path: str | None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
    src_lang: str = "",
    tgt_lang: str = "",
) -> str:
    """Return sha256(input_bytes + config_bytes_if_any + behavioral_flags).

    Behavioral CLI flags that affect the produced output bytes (frontmatter
    on/off, concurrency for batch, language-detection, LQA, restoration,
    glossary, glossary-max-terms, src_lang, tgt_lang) are mixed into the
    digest so a flag change invalidates the cached output. See T24a.

    ``src_lang`` and ``tgt_lang`` are included so that translating the same
    input to two different target languages does not produce a cache
    collision (OL#8).
    """
    h = hashlib.sha256()
    h.update(input_path.read_bytes())
    if config_path:
        cfg = Path(config_path)
        if cfg.exists():
            h.update(cfg.read_bytes())
    h.update(f"|fm={int(add_frontmatter)}".encode())
    h.update(f"|con={int(concurrency)}".encode())
    h.update(f"|det={int(detect_language)}".encode())
    h.update(f"|lqa={int(lqa_enabled)}".encode())
    h.update(f"|nres={int(no_restoration)}".encode())
    h.update(f"|nglo={int(no_glossary)}".encode())
    h.update(f"|glo={glossary or ''}".encode())
    h.update(f"|gmt={int(glossary_max_terms)}".encode())
    h.update(f"|src={src_lang}".encode())
    h.update(f"|tgt={tgt_lang}".encode())
    return h.hexdigest()


def _check_cache(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    no_cache: bool = False,
    ext: str | None = None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
    src_lang: str = "",
    tgt_lang: str = "",
) -> bool:
    """If cached, copy ``<input_stem><ext>`` to ``output_path`` and return True.

    Honors ``--no-cache``: returns False without touching the cache.
    """
    if no_cache:
        return False
    if ext is None:
        ext = input_path.suffix
    key = _cache_key(
        input_path, config_path,
        add_frontmatter=add_frontmatter,
        concurrency=concurrency,
        detect_language=detect_language,
        lqa_enabled=lqa_enabled,
        no_restoration=no_restoration,
        no_glossary=no_glossary,
        glossary=glossary,
        glossary_max_terms=glossary_max_terms,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
    )
    cache_file = _cache_root() / f"{key}{ext}"
    if cache_file.exists():
        target = output_path / input_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cache_file, target)
        _cache_logger.info(f"Cache hit: {cache_file} -> {target}")
        return True
    return False


def _write_cache(
    input_path: Path,
    output_path: Path,
    config_path: str | None,
    no_cache: bool = False,
    ext: str | None = None,
    add_frontmatter: bool = True,
    concurrency: int = 5,
    detect_language: bool = True,
    lqa_enabled: bool = False,
    no_restoration: bool = False,
    no_glossary: bool = False,
    glossary: str | None = None,
    glossary_max_terms: int = 5,
    src_lang: str = "",
    tgt_lang: str = "",
) -> None:
    """Copy the produced output into the cache for next run.

    Honors ``--no-cache``: no-op.
    """
    if no_cache:
        return
    output_file = output_path / input_path.name
    if not output_file.exists():
        return
    if ext is None:
        ext = input_path.suffix
    key = _cache_key(
        input_path, config_path,
        add_frontmatter=add_frontmatter,
        concurrency=concurrency,
        detect_language=detect_language,
        lqa_enabled=lqa_enabled,
        no_restoration=no_restoration,
        no_glossary=no_glossary,
        glossary=glossary,
        glossary_max_terms=glossary_max_terms,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
    )
    cache_file = _cache_root() / f"{key}{ext}"
    cache_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy(output_file, cache_file)
    _cache_logger.debug(f"Cache miss: wrote {cache_file}")


def _clear_ol_cache() -> int:
    """Remove all cached OL files. Returns the number of files removed."""
    root = _cache_root()
    if not root.exists():
        return 0
    count = sum(1 for _ in root.iterdir())
    shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return count
