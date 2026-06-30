"""generate_report MCP tool for Omni-Localizer.

Generate HTML and CSV quality reports from translation warnings and
model cost entries using Jinja2 templates.
"""
from __future__ import annotations

import json

from ol_mcp.auth import auth_failure_response, check_auth
from ol_mcp.rate_limiter import check_rate_limit, rate_limit_failure_response
from ol_mcp.security import get_default_validator
from ol_mcp.tools import (
    _error_response,
    _register_tool,
    _success_response,
    GenerateReportInput,
    mcp_error_boundary,
)


@_register_tool(
    "generate_report",
    GenerateReportInput,
    "Generate HTML and CSV quality reports from translation warnings and model costs. "
    "Writes report.html and report.csv to output_dir/<job_id>_*. "
    "Set force=true to overwrite existing reports.",
)
@mcp_error_boundary
async def generate_report(params: GenerateReportInput) -> str:
    rate_ok, rate_err = check_rate_limit()
    if not rate_ok:
        return json.dumps(rate_limit_failure_response(), ensure_ascii=False)
    auth_ok, _ = check_auth(params.shared_secret)
    if not auth_ok:
        return json.dumps(auth_failure_response(), ensure_ascii=False)

    vresult = get_default_validator().validate_path(params.output_dir)
    if not vresult.success:
        return json.dumps(
            _error_response(
                "OL_INVALID_INPUT", f"OL_PATH_NOT_ALLOWED: {vresult.error}"
            ),
            ensure_ascii=False,
        )

    try:
        from ol_lqa.report import (
            ModelCostEntry,
            WarningEntry,
            generate_report as _gen_report,
        )
    except ImportError as e:
        return json.dumps(
            _error_response(
                "OL_DEPS_MISSING",
                f"ol_lqa.report not importable ({e})",
            ),
            ensure_ascii=False,
        )

    try:
        warnings = [
            WarningEntry(**w.model_dump()) for w in params.warnings
        ]
        model_costs = {
            mc.model_name: ModelCostEntry(
                model_name=mc.model_name,
                prompt_tokens=mc.prompt_tokens,
                completion_tokens=mc.completion_tokens,
                cost_per_1k_tokens=mc.cost_per_1k_tokens,
            )
            for mc in params.model_costs
        }
        result = _gen_report(
            output_dir=params.output_dir,
            job_id=params.job_id,
            force=params.force,
            warnings=warnings,
            model_costs=model_costs,
        )
        return json.dumps(
            _success_response(
                {"html_path": result.get("html"), "csv_path": result.get("csv")}
            ),
            ensure_ascii=False,
        )
    except FileExistsError as e:
        return json.dumps(
            _error_response("OL_FILE_EXISTS", str(e)),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            _error_response("OL_GENERATE_REPORT_FAILED", str(e)),
            ensure_ascii=False,
        )
