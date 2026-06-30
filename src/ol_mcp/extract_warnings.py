"""extract_warnings MCP tool for Omni-Localizer.

Reads a file (MD or XLIFF) and returns structured WarningEntry objects
suitable for direct use with the generate_report tool. Closes the
text-vs-structured gap that previously forced agents to parse regex
matches manually and risk TypeError on field-name mismatches.

Wraps the shared regex patterns from cli._warning_extractor (single
source of truth for OL warning markers).
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    ExtractWarningsInput,
    mcp_error_boundary,
)


@_register_tool(
    "extract_warnings",
    ExtractWarningsInput,
    "Read a file (MD or XLIFF) and extract OL warning markers as structured "
    "WarningEntry objects. Use the result directly with generate_report."
)
@mcp_error_boundary
async def extract_warnings(params: ExtractWarningsInput) -> str:
    """Read *file_path* and return structured warnings.

    The output JSON is a list of plain dicts matching the WarningEntry
    schema. Pass them directly to generate_report's `warnings` parameter
    (or merge with other entries).

    Note: this differs from the `extract-warnings` CLI subcommand which
    outputs plain text. The MCP tool returns structured data because MCP
    callers (LLM agents) need to chain it with generate_report, which
    takes structured input.
    """
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    from cli._warning_extractor import extract_warnings_from_file
    try:
        entries = extract_warnings_from_file(params.file_path)
    except FileNotFoundError:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT",
                f"file not found: {params.file_path}",
            ),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            _error_response("OL_EXTRACT_WARNINGS_FAILED", str(e)),
            ensure_ascii=False,
        )

    # Convert dataclass to dict so the result is JSON-serializable
    # without depending on the consumer having WarningEntry imported.
    content = {
        "warnings": [
            {
                "file_path": e.file_path,
                "line_number": e.line_number,
                "warning_type": e.warning_type,
                "severity": e.severity,
                "model": e.model,
                "cost": e.cost,
                "source_text": e.source_text,
                "target_text": e.target_text,
                "reference": e.reference,
            }
            for e in entries
        ],
        "source_file": params.file_path,
        "count": len(entries),
    }
    return json.dumps(_success_response(content), ensure_ascii=False)
