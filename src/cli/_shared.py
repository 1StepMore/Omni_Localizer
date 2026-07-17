"""Shared CLI utilities used by cli submodules.

These are extracted from ol_cli.py to break the circular import:
ol_cli → cli.translate_md → ol_cli.
This module has zero dependencies on ol_cli or other cli submodules.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock as _SeamMagicMock

import typer

from ol_logging.core import get_logger

logger = get_logger("cli")

_interrupted = False


def read_with_encoding(path: Path) -> str:
    """Read a text file with automatic encoding detection.

    Detection order:
    1. BOM signature (UTF-16-LE, UTF-16-BE, UTF-8-SIG)
    2. ``chardet`` if available and confidence >= 0.8
    3. UTF-8 fallback

    Args:
        path: Path to the file to read.

    Returns:
        File contents as a decoded string.
    """
    raw = path.read_bytes()

    # 1. BOM detection
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")

    # 2. Optional chardet detection
    try:
        import chardet  # noqa: PLC0415 — optional dependency

        result = chardet.detect(raw)
        if result.get("confidence", 0) >= 0.8 and result.get("encoding"):
            try:
                return raw.decode(result["encoding"])
            except (LookupError, UnicodeDecodeError):
                pass
    except ImportError:
        pass

    # 3. UTF-8 fallback
    return raw.decode("utf-8")


def _sigint_handler(signum, frame):
    global _interrupted
    _interrupted = True
    typer.echo("\nReceived Ctrl+C - finishing in-flight files, no new starts...")


class ExitCode:
    SUCCESS = 0
    PIPELINE_ERROR = 1
    CLI_USAGE_ERROR = 2
    INTERRUPTED = 3
    QUALITY_GATE_BLOCKED = 4


class OLQualityGateBlockedError(Exception):
    """Raised when a quality gate blocks the pipeline from proceeding."""
    pass


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


_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

# Well-known API key env vars — used as fallback when no config file is found.
_KNOWN_API_KEY_VARS: tuple[str, ...] = (
    "ZHIPU_API_KEY",
    "AGNES_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "OPENCODE_GO_KEY",
    "OPENAI_API_KEY",
)


def precheck_api_keys(config_path: str | None) -> None:
    """Fail fast if a required API key env var is missing.

    Two-stage check:
    1. If a config file is found, scan it for ``${VAR}`` placeholders
       and verify each is set in the environment.
    2. If no config file can be resolved, check well-known API key env
       vars directly as a fallback guard.

    Both stages are intentionally lightweight — they must NOT import
    ``ol_pool.router`` (which takes ~30s on cold start via
    ``import litellm``) and must NOT import ``ol_config.schema``
    (which would load pydantic).

    Skipped when:
      - ``OMNI_TEST_FAKE_LLM=1`` (test seam — no real keys needed)
      - ``OMNI_RUN_REAL_LLM=1`` (explicit opt-in to network calls)
    """
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        return
    if os.environ.get("OMNI_RUN_REAL_LLM") == "1":
        return

    resolved = config_path or os.environ.get(
        "OL_CONFIG_PATH", "config/default.yaml"
    )
    cfg_file = Path(resolved)

    # Stage 1: config-file-based check
    if cfg_file.is_file():
        try:
            text = cfg_file.read_text(encoding="utf-8")
        except OSError:
            text = ""

        required: set[str] = set()
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            required.update(_ENV_VAR_RE.findall(line))

        if required:
            missing = sorted(v for v in required if v not in os.environ)
            if missing:
                typer.echo(
                    "Error: required API key(s) not set in environment: "
                    + ", ".join(missing)
                    + f"  (referenced as ${{...}} in {cfg_file})",
                    err=True,
                )
                _hint_fake_llm()
                raise typer.Exit(code=ExitCode.PIPELINE_ERROR)
            return

    # Stage 2: fallback — check known API key vars directly.
    # Catches the case where the default config path is CWD-relative
    # and the user runs from a different directory. Without this
    # fallback, precheck_api_keys would silently return, then
    # import litellm (~30s) would hang before the real error.
    missing_known = sorted(v for v in _KNOWN_API_KEY_VARS if v not in os.environ)
    if len(missing_known) == len(_KNOWN_API_KEY_VARS):
        typer.echo(
            "Error: no LLM API keys configured. "
            "Set at least one of: "
            + ", ".join(_KNOWN_API_KEY_VARS),
            err=True,
        )
        _hint_fake_llm()
        raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


def _hint_fake_llm() -> None:
    typer.echo(
        "Hint: set OMNI_TEST_FAKE_LLM=1 to skip real LLM calls, "
        "or export the missing variables (e.g. `export ZHIPU_API_KEY=...`).",
        err=True,
    )


# Translation failure tracking — set when a unit falls back to source text
_had_translation_failures: bool = False


def mark_translation_failure() -> None:
    """Record that at least one translation unit fell back to source text.

    Used by CLI handlers to exit with a non-zero code when all LLM providers
    fail for any unit.
    """
    global _had_translation_failures
    _had_translation_failures = True


def had_translation_failures() -> bool:
    """Return whether any translation unit fell back to source text."""
    return _had_translation_failures


def reset_translation_failures() -> None:
    """Reset the failure flag (for test isolation between runs)."""
    global _had_translation_failures
    _had_translation_failures = False


# Module-level guard to prevent duplicate warnings within a process
_fake_llm_warned = False


def warn_fake_llm_mode() -> None:
    """Print a one-time stderr warning when FAKE_LLM mode is active.

    Fired by CLI commands that use ModelPool or _FakeModelPool when
    OMNI_TEST_FAKE_LLM=1. The warning is written to stderr (not stdout)
    so it does not pollute JSON output, and fires only once per process
    to avoid duplication in batch sessions.

    To suppress: unset OMNI_TEST_FAKE_LLM. There is intentionally no
    other override — users running with FAKE_LLM should see this
    confirmation that output is not real.
    """
    global _fake_llm_warned
    if _fake_llm_warned:
        return
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        typer.echo(
            "WARNING: OMNI_TEST_FAKE_LLM=1 is set — using fake LLM responses. "
            "Output is NOT a real translation. Unset the env var for real translations.",
            err=True,
        )
        _fake_llm_warned = True


# ---------------------------------------------------------------------------
# __version__ — moved here from ol_cli.py to break circular import
# (ol_cli → cli → frontmatter → ol_cli)
# ---------------------------------------------------------------------------
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("omni-localizer")
except Exception:
    __version__ = "0.0.0+unknown"
