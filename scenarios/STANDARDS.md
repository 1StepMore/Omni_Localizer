# Validation Standards — OL Translation Scenario Library

This is the citable standards reference for the OL translation scenario
library under `Omni_Localizer/scenarios/`. Every scenario step that
enforces a quality bar cites the exact standard it checks as
`standard: STANDARDS.md#<anchor-id>`. The bars are grouped into the two
named families shared by the whole suite (draft D13): **AGENT-SURFACE**
(agent-user conformance — every OL tool works as an agent would use it)
and **HUMAN-QUALITY** (human-result quality — OL's translation output
satisfies human end-users).

These are **repo-scoped** bars for the OL module: they refine the
suite-level `scenarios/STANDARDS.md` anchors to the specific surfaces and
thresholds of `Omni_Localizer` (the 21-tool MCP registry in
`ol_mcp.tools`, the `ol` CLI, and the translation/judging/quality-gate
channels). The suite-level file remains the cross-module bar; this file
is what the OL library's `standard:` citations resolve against.

OL translation scenarios are **tier 2** (real LLM key required): they are
`requires_env`-gated on the provider keys OL's model pool reads from
`config/default.yaml` (`ZHIPU_API_KEY`, `AGNES_API_KEY`,
`NVIDIA_NIM_API_KEY`, `OPENCODE_GO_KEY`, `OPENCODE_GO_BASE_URL`), so they
report `unconfigured` when the keys are absent — never a fake pass.

## AGENT-SURFACE

Mission axis 1: validation proves every agent-facing surface — the live
OL MCP tools (`ol_mcp.tools` registry, 21 tools) and the `ol` CLI — works
as an agent-user would use it: schema-shaped params accepted, structured
JSON returned, clear parseable errors on bad input, path-security denial
honored.

### Tool contract conformance {#tool-contract}

Every OL tool accepts its schema-shaped parameters, executes against the
real surface, and returns a structured result carrying the expected keys
— no dead tools, no shape drift between the live registry and the shipped
behavior. OL's MCP tools take a single typed input model (e.g.
`TranslateInput`, `JudgeInput`, `LoadGlossaryInput` from `ol_mcp.tools`)
and return a JSON string.

**How to check:** in-process call of the real `ol_mcp.tools` function
with its input model (e.g. `asyncio.run(translate_md_text(params=
TranslateInput(content=..., source_lang="en", target_lang="zh")))`), then
grade `success: true` + key presence against the tool's declared result
shape (`translated` / `source_lang` / `target_lang` for
`translate_md_text`, `output_path` / `units_processed` for
`translate_xliff`, `judge_scores` for `judge_text`, `glossary` /
`term_count` for `load_glossary`). Citable as `standard:
STANDARDS.md#tool-contract`.

### JSON parseability {#json-parseable}

Every tool result and every CLI JSON output parses as valid JSON — an
agent-user's `json.loads` must never fail on OL's own output. A response
that cannot be parsed is a contract break regardless of content.

**How to check:** `json.loads` on the captured output; a
`JSONDecodeError` fails the step. Citable as `standard:
STANDARDS.md#json-parseable`.

### Error clarity {#error-clarity}

Failures are reported as clear, parseable, agent-readable error messages
that name the failing tool and the offending parameter — never raw
stack-trace soup. OL's `@mcp_error_boundary` (in `ol_mcp/_errors.py`)
returns opaque, stable codes (`OL_INVALID_INPUT`, `OL_PATH_DENIED`,
`OL_MCP_NOT_CONFIGURED`, `OL_FILE_NOT_FOUND`, `OL_INTERNAL_ERROR`, ...)
with user-safe messages and no internals.

**How to check:** invoke the tool with a deliberately bad input (e.g. a
same-language pair to `judge_text`, an out-of-allowlist path to
`load_glossary`); expect an error payload that names the code + reason
and does NOT contain a `Traceback (most recent call last)` frame. Citable
as `standard: STANDARDS.md#error-clarity`.

### Path security {#path-security}

Path-taking tools deny access outside the configured allowlist. OL's
`PathValidator` (`ol_mcp/security.py`) reads `MCP_ALLOWED_DIRECTORIES`,
then `OL_MCP_ALLOWED_DIRS`, then `OL_ALLOWED_DIRECTORIES` (precedence
order); unset → the validator raises `MCPNotConfiguredError` (error code
`OL_MCP_NOT_CONFIGURED`; a `ValueError` subclass) (fail-CLOSED; no cwd +
`/tmp` default). An out-of-allowlist path MUST
be rejected with `OL_PATH_DENIED`, never silently accepted.

**How to check:** call a path-taking tool (e.g. `load_glossary`,
`translate_xliff`) with a path outside the allowlist; expect a denial
error naming the path with `OL_PATH_DENIED`. Citable as `standard:
STANDARDS.md#path-security`.

### Exit codes {#exit-codes}

CLI commands exit 0 on success and a nonzero code on failure, with the
failure reason on stderr — so scripts and agents can branch on the code.
The `ol` CLI (Typer) follows this contract for `translate-md`,
`translate-xliff`, `translate-batch`, and `extract-warnings`.

**How to check:** `expect: {exit_code: 0}` on success paths;
`expect: {exit_code: 1, stderr_has: [...]}` on guarded failure paths.
Citable as `standard: STANDARDS.md#exit-codes`.

### Graceful empty input {#empty-input-graceful}

Empty or whitespace-only input to a translation tool is handled
gracefully: the call completes without raising out of the surface, and
the response is always a structured JSON payload carrying a `success`
key — never a raw traceback, never a hung process. Graceful handling
means the failure mode (if any) is agent-readable and parseable.

**How to check:** call `translate_md_text` with `content=""` and with
whitespace-only content; expect a JSON response containing `"success"`
and no `Traceback` in the payload. Citable as `standard:
STANDARDS.md#empty-input-graceful`.

## HUMAN-QUALITY

Mission axis 2: a green translation run must prove the output meets the
end-user bar — quality is judged and gates run, and their results are
surfaced to the caller as structured warnings, never silently dropped.

### Judge threshold {#judge-threshold}

`judge_text` returns a numeric overall score on the 0-100 scale plus a
rubric breakdown (`judge_scores` with `adequacy`, `fluency`,
`terminology_consistency`, `format_preservation`). A valid judgment run
returns the score map with `success: true`; the LQA channel
(`ol_lqa.judge.JudgeService`, score 0-100 with `lqa_threshold` default
7.0) is the engine that backs the tool.

**How to check:** call `judge_text` on a known en→zh pair; expect
`"success": true` with `judge_scores` containing `adequacy`. Citable as
`standard: STANDARDS.md#judge-threshold`.

### Quality gate warnings {#quality-gate-warnings}

OL runs eight post-translation quality gates (OL#56: inline tags,
terminology, length ratio, locale, source copy, source script fragments,
protocol artifacts, terms audit). Their results are surfaced as
structured warnings — `warnings` in the `translate_md_text` response and
per-unit `<note>` elements in `translate_xliff` output — never silently
dropped, never fatal on their own (non-blocking).

**How to check:** after a glossary-driven `translate_md_text`, expect the
response to carry a `warnings` key (list) alongside `translated`;
warnings fire as `OL_WARN`-style entries when a gate trips. Citable as
`standard: STANDARDS.md#quality-gate-warnings`.
