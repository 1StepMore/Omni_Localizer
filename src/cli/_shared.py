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


def precheck_api_keys(config_path: str | None) -> None:
    """Fail fast only when NO usable API key env var is configured.

    Scans the config YAML for ``${VAR}`` placeholders. The pool is
    BYOK with several providers per role (``router.partition_usable_models``
    keeps the models whose refs resolve and skips the rest as
    fallbacks), so holding exactly ONE provider key is a valid
    configuration. Only the zero-key case is fail-closed, and the
    error distinguishes the two distinct mistakes:

      (a) no ``*_API_KEY``-shaped var is set at all → nothing is
          configured; list the refs this config needs + point at docs.
      (b) key-like vars ARE set but none is referenced by this config
          (e.g. an ``OPENAI_API_KEY`` against an AMD/Zhipu pool) →
          configured-but-mismatched; name both sides.

    The pre-check is intentionally a lightweight regex scan on the
    raw YAML text — it must NOT import ``ol_pool.router`` (which
    takes ~30s on cold start via ``import litellm``). The only OL
    import it needs is ``ol_config.resolver`` (the shared config-path
    resolver), and it is function-level so the FAKE_LLM fast path above
    never pays for it; on the real path ``load_config`` loads the same
    package's pydantic schema moments later anyway. The whole point is
    to give the user a fast, clear error instead of a multi-minute
    hang followed by silent garbage output.

    Skipped when:
      - ``OMNI_TEST_FAKE_LLM=1`` (test seam — no real keys needed)
      - ``OMNI_RUN_REAL_LLM=1`` (explicit opt-in to network calls)
      - The config file cannot be located or read (in that case we
        let the existing code path emit a clearer error later)
      - The config references no ``${VAR}`` at all
    """
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        return
    if os.environ.get("OMNI_RUN_REAL_LLM") == "1":
        return

    from ol_config.resolver import resolve_config_path

    cfg_file = resolve_config_path(config_path)
    if not cfg_file.is_file():
        return

    try:
        text = cfg_file.read_text(encoding="utf-8")
    except OSError:
        return

    required: set[str] = set()
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        required.update(_ENV_VAR_RE.findall(line))
    if not required:
        return

    # A var present but set to "" counts as absent (matches
    # ``router._unresolved_env_vars``, which uses os.environ.get).
    if any(os.environ.get(var) for var in required):
        # One working provider is enough: the unset refs are fallbacks
        # the router silently skips. Do not fail the run for those.
        return

    expected = ", ".join(sorted(required))
    # Key-like = env names shaped like a provider key. Compared on the
    # name suffix so a mismatch (case b) is distinguishable from a truly
    # empty environment (case a).
    key_like = sorted(
        name for name, value in os.environ.items()
        if name.endswith("_API_KEY") and value
    )

    if not key_like:
        typer.echo(
            "Error: no provider API key is configured. "
            f"This config references: {expected}. "
            "Set at least one of them (e.g. `export AMD_API_KEY=...`).",
            err=True,
        )
        typer.echo(
            "Hint: see SETUP.md and .env.example for setup details, "
            "or run `ol init` to regenerate a config and print the keys "
            "it needs.",
            err=True,
        )
    else:
        found = ", ".join(key_like)
        typer.echo(
            "Error: the configured API key(s) do not match this model "
            f"pool. Environment has: {found}. This pool expects: {expected}.",
            err=True,
        )
        typer.echo(
            "Hint: export one of the pool's vars (e.g. "
            "`export AMD_API_KEY=...`), or point --config at a pool that "
            "uses the key you already have.",
            err=True,
        )

    typer.echo(
        "Hint: set OMNI_TEST_FAKE_LLM=1 to skip real LLM calls.",
        err=True,
    )
    raise typer.Exit(code=ExitCode.PIPELINE_ERROR)


def hint_init_suggestion() -> None:
    """Print a hint to run `ol init` when config loading/validation fails.

    Fired by `ol doctor` on any FAIL and by the translate commands when
    ``load_config`` raises a schema ``ValueError`` or ``FileNotFoundError``.
    Written to stderr so it never pollutes ``--json`` stdout.
    """
    typer.echo("Hint: run 'ol init' to generate a valid config/local.yaml", err=True)


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
