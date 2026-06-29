"""Shared CLI utilities used by cli submodules.

These are extracted from ol_cli.py to break the circular import:
ol_cli → cli.translate_md → ol_cli.
This module has zero dependencies on ol_cli or other cli submodules.
"""
from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock as _SeamMagicMock

import typer

from ol_logging.core import get_logger

logger = get_logger("cli")

_interrupted = False


def _sigint_handler(signum, frame):
    global _interrupted
    _interrupted = True
    typer.echo("\nReceived Ctrl+C - finishing in-flight files, no new starts...")


class ExitCode:
    SUCCESS = 0
    PIPELINE_ERROR = 1
    CLI_USAGE_ERROR = 2
    INTERRUPTED = 3


def _setup_signal_handler():
    signal.signal(signal.SIGINT, _sigint_handler)


def is_interrupted() -> bool:
    return _interrupted


def validate_input_file(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists():
        raise typer.BadParameter(f"Input file not found: {path}")
    if not file_path.is_file():
        raise typer.BadParameter(f"Input is not a file: {path}")
    return file_path


def _enforce_file_size(input_path: Path, max_size_mb: int = 50) -> None:
    """Reject files larger than max_size_mb."""
    size_mb = input_path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise typer.BadParameter(
            f"Input file {input_path.name} is {size_mb:.1f} MB, "
            f"exceeds limit of {max_size_mb} MB"
        )


def ensure_output_dir(path: str) -> Path:
    output_path = Path(path)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def output_json(
    success: bool,
    input_file: str,
    output_file: str | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
    error: str | None = None,
) -> None:
    """Output structured JSON to stdout."""
    result = {
        "success": success,
        "input_file": input_file,
    }
    if output_file:
        result["output_file"] = str(output_file)
    if source_lang:
        result["source_lang"] = source_lang
    if target_lang:
        result["target_lang"] = target_lang
    if error:
        result["error"] = error
    typer.echo(json.dumps(result, ensure_ascii=False))


def _apply_fake_llm_seam() -> None:
    """Test seam: when OMNI_TEST_FAKE_LLM=1, also stub ``span_aligner``.

    The OMNI_TEST_FAKE_LLM seam short-circuits the LLM call
    (``ModelPool.translate``) but does not cover the post-translation
    MD repair pipeline. Level 2 of that pipeline imports
    ``span_aligner.SpanProjector``, which constructs a HF transformer
    (``bert-base-multilingual-cased``) — that fails in hermetic CI
    (no API keys, no HF network).

    This helper installs a lightweight ``sys.modules['span_aligner']``
    stub whose ``SpanProjector.project`` is identity and ``align`` /
    ``align_spans`` return ``[]``. Idempotent: re-running it is a
    no-op (we mark the stub with a sentinel attribute).

    See ``docs/T14_LIMITATION.md`` for the full T14 history.
    """
    existing = sys.modules.get("span_aligner")
    if existing is not None and getattr(existing, "_omni_fake_seam", False):
        return

    _span_mod = _SeamMagicMock()
    _span_mod.SpanProjector = lambda *a, **k: _SeamMagicMock(
        project=lambda text, *a, **k: text,
        align=lambda *a, **k: [],
    )
    _span_mod.align_spans = lambda *a, **k: []
    _span_mod._omni_fake_seam = True
    sys.modules["span_aligner"] = _span_mod
