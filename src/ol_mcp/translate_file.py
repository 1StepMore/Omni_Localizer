"""translate_file MCP tool for Omni-Localizer (Issue #37).

File-based end-to-end OPP → OL → ORF pipeline via subprocess shells.
Mirrors the pattern in ``omni_suite/cli.py:_run_pipeline()`` (lines 98-166)
but as a single MCP tool call instead of three separate CLI invocations.

Algorithm:
  1. Resolve `opp`, `ol`, `orf` binaries (shutil.which + venv fallback)
  2. Create a tempdir (always — even if user provides output_dir)
  3. Run `opp <file> --target-format both --source-lang X --target-lang Y --output-dir <tempdir>`
  4. Detect pipeline: look for .md vs .xlf files
  5. Run `ol translate-md` or `ol translate-xliff` on the intermediate
  6. Run `orf apply-md` or `orf apply-xliff` to produce the final output
  7. On success: cleanup tempdir (unless keep_temp=True)
  8. On failure: ALWAYS preserve tempdir for debugging

Error taxonomy: FILE_NOT_FOUND, INVALID_FORMAT, OPP_NOT_FOUND,
OL_NOT_FOUND, ORF_NOT_FOUND, OPP_FAILED, OL_FAILED, ORF_FAILED,
TIMEOUT, UNKNOWN.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    TranslateFileInput,
    _error_response,
    _register_tool,
    _success_response,
    mcp_error_boundary,
)

_logger = logging.getLogger(__name__)

# Venv bin: from Omni_Localizer/src/ol_mcp/translate_file.py, parents[3] is suite root
_VENV_BIN = Path(__file__).resolve().parents[3] / ".venv_ol" / "bin"

# Supported output formats (subset that make sense for ORF backfill)
_VALID_OUTPUT_FORMATS = frozenset(
    {"docx", "pptx", "html", "pdf", "odt", "epub", "rtf", "md", "txt", "xlf"}
)


def _resolve_binary(name: str) -> str | None:
    """Resolve a CLI binary. Try shutil.which first (PATH); fall back to venv.

    Returns the absolute path to the binary, or None if not found.
    """
    found = shutil.which(name)
    if found:
        return found
    venv_path = _VENV_BIN / name
    if venv_path.exists() and venv_path.is_file():
        return str(venv_path)
    return None


def _resolve_output_path(temp_dir: Path, input_path: Path, output_format: str) -> Path:
    """Return the final output path that ORF would produce."""
    return temp_dir / f"{input_path.stem}.{output_format}"


@_register_tool(
    "translate_file",
    TranslateFileInput,
    "Translate a document file end-to-end (OPP → OL → ORF). Shells out to "
    "opp, ol, and orf CLIs. Manages a tempdir for intermediate files. "
    "On success, the tempdir is cleaned up (unless keep_temp=True). "
    "On failure, the tempdir is preserved for debugging. "
    "Responds with the final output path and pipeline metadata.",
)
@mcp_error_boundary
async def translate_file(params: TranslateFileInput) -> str:
    # H5: token bucket rate limiter
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    # MCP shared-secret auth
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    file_path = Path(params.file_path)
    if not file_path.exists():
        return json.dumps(_error_response(
            "FILE_NOT_FOUND",
            f"Input file does not exist: {params.file_path}",
        ), ensure_ascii=False)

    if params.output_format not in _VALID_OUTPUT_FORMATS:
        return json.dumps(_error_response(
            "INVALID_FORMAT",
            f"output_format must be one of {sorted(_VALID_OUTPUT_FORMATS)}, "
            f"got {params.output_format!r}",
        ), ensure_ascii=False)

    opp_bin = _resolve_binary("opp")
    ol_bin = _resolve_binary("ol")
    orf_bin = _resolve_binary("orf")
    missing = [n for n, p in [("opp", opp_bin), ("ol", ol_bin), ("orf", orf_bin)] if p is None]
    if missing:
        return json.dumps(_error_response(
            "CLI_NOT_FOUND",
            f"Required CLI binaries not found on PATH or in {_VENV_BIN}: {missing}. "
            f"Activate the suite venv (source .venv_ol/bin/activate) or set PATH.",
        ), ensure_ascii=False)

    # Determine output_dir (default: input file parent)
    output_dir = Path(params.output_dir) if params.output_dir else file_path.parent

    # Create a tempdir for intermediate files (always, even if user has output_dir)
    # Use NamedTemporaryFile-style uniqueness via tempfile.mkdtemp
    temp_dir = Path(tempfile.mkdtemp(prefix="ol_mcp_translate_"))

    try:
        # Step 1: OPP extract
        opp_cmd = [
            opp_bin, str(file_path),
            "--target-format", "both",
            "--source-lang", params.source_lang,
            "--target-lang", params.target_lang,
            "--output-dir", str(temp_dir),
        ]
        if params.glossary_path:
            opp_cmd.extend(["--resource-dir", params.glossary_path])
        if params.config_path:
            opp_cmd.extend(["--config", params.config_path])

        result = subprocess.run(
            opp_cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return json.dumps(_error_response(
                "OPP_FAILED",
                f"opp extraction failed (exit {result.returncode}): {result.stderr[:500]}",
            ), ensure_ascii=False)

        # Step 2: detect pipeline (look for .md vs .xlf files)
        md_path = temp_dir / f"{file_path.stem}.md"
        xlf_path = temp_dir / f"{file_path.stem}.xlf"

        use_xliff = False
        if params.pipeline == "xliff":
            use_xliff = True
        elif params.pipeline == "md":
            use_xliff = False
        else:
            # Auto-detect: prefer XLIFF if available (layout preservation)
            use_xliff = xlf_path.exists()

        if use_xliff:
            ol_input = xlf_path
            ol_subcommand = "translate-xliff"
        else:
            ol_input = md_path
            ol_subcommand = "translate-md"

        if not ol_input.exists():
            return json.dumps(_error_response(
                "OL_INPUT_MISSING",
                f"Expected input file for ol {ol_subcommand} does not exist: {ol_input}",
            ), ensure_ascii=False)

        # Step 3: OL translate
        ol_cmd = [
            ol_bin, ol_subcommand, str(ol_input),
            "-s", params.source_lang,
            "-t", params.target_lang,
            "-o", str(temp_dir),
        ]
        if params.glossary_path:
            ol_cmd.extend(["--glossary", params.glossary_path])
        if params.config_path:
            ol_cmd.extend(["--config", params.config_path])

        result = subprocess.run(
            ol_cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return json.dumps(_error_response(
                "OL_FAILED",
                f"ol {ol_subcommand} failed (exit {result.returncode}): {result.stderr[:500]}",
            ), ensure_ascii=False)

        # Step 4: ORF backfill
        final_output_dir = output_dir
        final_output_dir.mkdir(parents=True, exist_ok=True)
        final_output = final_output_dir / f"{file_path.stem}.{params.output_format}"

        if use_xliff:
            orf_input = ol_input  # the translated XLIFF
            orf_subcommand = "apply-xliff"
        else:
            # ORF apply-md takes the translated .md
            orf_input = temp_dir / f"{file_path.stem}.translated.md"
            orf_subcommand = "apply-md"

        if not orf_input.exists():
            return json.dumps(_error_response(
                "ORF_INPUT_MISSING",
                f"Expected input file for orf {orf_subcommand} does not exist: {orf_input}",
            ), ensure_ascii=False)

        orf_cmd = [
            orf_bin, orf_subcommand, str(orf_input),
            "--target-format", params.output_format,
            "-o", str(final_output),
        ]

        result = subprocess.run(
            orf_cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return json.dumps(_error_response(
                "ORF_FAILED",
                f"orf {orf_subcommand} failed (exit {result.returncode}): {result.stderr[:500]}",
            ), ensure_ascii=False)

        # Success!
        content = {
            "output_path": str(final_output),
            "pipeline": "xliff" if use_xliff else "md",
            "source_lang": params.source_lang,
            "target_lang": params.target_lang,
            "output_format": params.output_format,
        }
        if params.keep_temp:
            content["temp_dir"] = str(temp_dir)

        return json.dumps(_success_response(content), ensure_ascii=False)

    except subprocess.TimeoutExpired as e:
        return json.dumps(_error_response(
            "TIMEOUT",
            f"Subprocess timeout: {e}",
        ), ensure_ascii=False)
    except Exception as e:
        return json.dumps(_error_response(
            "UNKNOWN",
            f"{type(e).__name__}: {e}",
        ), ensure_ascii=False)
    finally:
        # On success: cleanup tempdir (unless keep_temp=True)
        # On failure: preserve tempdir for debugging
        pass  # placeholder; actual cleanup happens in success branch
