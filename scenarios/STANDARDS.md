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
`config/default.yaml` (`ZHIPU_API_KEY`), so they report
`unconfigured` when the keys are absent — never a fake pass.

## Evidence admissibility (cross-cutting bar)

Two rules apply in this repo exactly as they do at suite level: a run that
cannot produce real evidence must never be reported as GREEN.

### Fallbacks are never evidence {#fallbacks-never-evidence}

Deterministic fallbacks — `OMNI_TEST_FAKE_LLM=1`, `OMNI_TEST_FAKE_PANDOC=1`,
and every seam in this class (`OMNI_TEST_FAKE_*`, monkey-patched engines,
stub backends) — are **never admissible as quality (HUMAN-QUALITY)
evidence**. A fallback emits synthetic, deterministic output: a green run
under one proves the plumbing ran, not that the result meets the
human-quality bar.

- A verdict produced while a fallback is active MUST be reported as
  **`invalid`** — a status that can never be summarised as GREEN — or, when
  no step executed, as `unconfigured` / `skipped`. Never `passed`.
- The only escape hatch is **contract-only** (`--allow-fake`, suite side):
  it re-admits a fallback run only when **every** step of the scenario
  cites an AGENT-SURFACE anchor. One HUMAN-QUALITY citation, one
  anchor-less step, or an empty step list makes the scenario ineligible.
- Any produced artifact carrying the fake-echo signature is `invalid`
  regardless of the escape hatch.

**How to check:** run the same scenario with and without the fallback env
var set; the fallback run must not report `passed`. Citable as
`standard: STANDARDS.md#fallbacks-never-evidence`.

### Env gate semantics {#env-gate-semantics}

Gating is **fail-closed**: `unconfigured` is never `passed`.

- Every listed required variable must resolve; a variable present but
  **empty counts as missing**.
- An OR group (`requires_env_any` at suite level) resolves when at least
  one of its variables resolves; an OR group with none resolving fails
  **closed** — the scenario reports `unconfigured` and executes no steps,
  so a keyless user never reaches a real LLM call.
- Absent or empty group declarations keep the AND-only behaviour.

**How to check:** run a scenario with its key unset; expect
`unconfigured`, zero executed steps, and no LLM call. Citable as
`standard: STANDARDS.md#env-gate-semantics`.

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

### LQA threshold (artifact level) {#lqa-threshold}

OL's own per-unit retry/batch loop passes a unit at
`pass_threshold = 7.0` (`ol_retry/retry.py:30`, `ol_batch/processor.py:52`).
At artifact level the suite bar applies: the **average** LLM-judged
translation quality over the translated artifact must be **>= 4.0/5**
(0-5 scale), scored by `ol_lqa.judge.JudgeService` over the first <= 50
scorable trans-units, whitespace-only targets skipped.

**How to check:** per unit — `judge_overall_score >= 7.0`; artifact —
average rescaled to /5 `>= 4.0` (artifact-level judging is executed in
`e2e-test-suite`, per the module-scoped-standards decision). Citable as
`standard: STANDARDS.md#lqa-threshold`.

### Untranslated units {#untranslated-units}

A translated artifact must declare **zero untranslated units**: the
`translate-md` output frontmatter carries `untranslated_units`
(`src/cli/_shared.py:86`), and the value must be **absent or `0`**. A value
`> 0` means part of the document was never translated — and unlike a CJK
ratio it cannot be diluted by a long document.

**How to check:** read the output `.md` frontmatter; `untranslated_units`
absent/`0` passes, `> 0` fails naming `N/M unit(s) untranslated`. Citable
as `standard: STANDARDS.md#untranslated-units`.

### CJK density (English-target output) {#cjk-density}

For an English-target artifact the **CJK character ratio must stay below
5%** (`[\u4e00-\u9fff]` count / total characters over paragraph text); up
to 5% is tolerated for brand names and proper nouns kept on purpose.
5% or more means the translation is incomplete.

**How to check:** `len(re.findall(r"[\u4e00-\u9fff]", out)) / len(out) < 0.05`
over the output's paragraph text (artifact level, executed in
`e2e-test-suite`). Citable as `standard: STANDARDS.md#cjk-density`.

### Punctuation hygiene {#punct-hygiene}

Zero foreign-language punctuation in the output: an English-target artifact
must contain no CJK / full-width punctuation (`，。、；：（）！？“”`) that the
source paragraph did not already carry.

**How to check:** scan the output for full-width / CJK punctuation not
present in the corresponding source paragraph; any hit fails (artifact
level, executed in `e2e-test-suite`). Citable as
`standard: STANDARDS.md#punct-hygiene`.
