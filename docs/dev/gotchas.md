# OL known issues / gotchas (moved from AGENTS.md, #162)

Quick pointers for the ones every agent hits; the issue-linked details
live further down.

- **E2E-65**: prompt injection strip in Level 1 repair. Don't strip
  `CRITICAL/IMPORTANT/NOTE: Output ONLY...` patterns yourself; the
  repair handles it.
- **E2E-74**: `ModelPool.translate(context=...)` — `context=None` and
  `context=dict` both work (pre-fix: UnboundLocalError); `context=str`
  is used verbatim (pre-fix: AttributeError from str.get()).
- **E2E-83**: large content (>~50K chars) emits a WARNING log but
  is not blocked.
- **LQA**: `enable_lqa: true` in config triggers auto-judging with
  retry on low scores. Slow.
- **TM/TB/SG**: Translation memory + glossary injection. Set
  `glossary_path` in config or pass `--glossary <path>`.
- **Routing**: litellm Router randomizes within role group. If you
  need deterministic model selection, set `priority: 1` on only one
  model per role.
- **Circuit breaker**: 5 consecutive failures → open for 60s.

## OL#53: Polish language guard

`polish_translated_units()` and `polish_md_text()` now skip corrections
that would revert translated text back to the source language (zh→en
direction). The `has_source_language_residual()` helper is exported
from `ol.pool` for reuse.

## OL#54: Truncation detection

`ModelPool.translate()` now applies a secondary truncation heuristic
when the API reports `finish_reason="stop"` but the output looks
incomplete (trailing ellipsis, non-terminal punctuation on long inputs,
or `completion_tokens >= 90%` of `max_tokens`). `judge()` and
`profile()` fail-closed on `finish_reason="length"`.

## OL#55: XLIFF raw XML tag normalization

XLIFF Level 1 repair normalizes raw LLM-emitted inline tags
(`<x/>`, `<bx/>`, `<ex/>`) back to placeholders when a `shield_map` is
available. Level 4 safe fallback is now bx/ex-pair-aware and avoids
duplicating tag halves already restored by Level 3.

## OL#56: Quality gates

Eight config-driven checks run after translation/repair and append
non-blocking warnings to the output (the terms audit is a separate
`verify-terms` tool, not a pipeline gate):

| Gate | Description | Warning codes |
|------|-------------|---------------|
| `inline_tags` | Verify `<bx>`, `<ex>`, `<x>` tag parity between source and target | `INLINE_TAG_MISMATCH` |
| `terminology` | Detect mixed source/glossary term usage in target | `TERMINOLOGY_INCONSISTENCY` |
| `length_ratio` | Check translated/source length ratio is within bounds | `LENGTH_RATIO` |
| `locale` | Currency mixing, CJK date leakage, digit grouping (EU vs US), GB/US spelling | `CURRENCY_MIXING`, `DATE_LEAKAGE`, `DIGIT_GROUPING`, `UNIT_SPELLING` |
| `source_copy` | Detect when LLM echoes source text back unchanged | `SOURCE_COPY` |
| `source_script_check` | Detect CJK characters that leaked into a non-CJK target locale | `SOURCE_SCRIPT_FRAGMENT` |
| `protocol_artifact_check` | Detect LLM protocol/metadata markers in translated text | `PROTOCOL_ARTIFACT` |
| `invented_token_check` | Detect model-invented glued tokens absent from the source (OL#158) | `INVENTED_TOKEN` |

Warnings are collected and returned in the `warnings` output field
(MCP) or appended to the output file as HTML comments / `<note>`
elements (CLI). Configure via `quality_gates:` in `config/default.yaml`
or override with `OL_LENGTH_RATIO_MIN`, `OL_LENGTH_RATIO_MAX`, and
`OL_TARGET_LOCALE` env vars.

On the MCP channel (`translate_md_text`, `translate_xliff`) a gate pass that
never ran is reported, not downgraded to a log line (issue #115). The response
carries `quality_gates: {"status": "ran" | "not_run" | "skipped", "reason": …}`;
`not_run` means the config was missing/unloadable or the gate invocation
raised, and it also appends `OL_GATES_NOT_RUN: <reason>` to `warnings`. Callers
opt out deliberately with `no_quality_gates: true`, which reports `skipped` plus
`OL_GATES_SKIPPED: …`. Gate *warnings* stay non-blocking in all three cases.
The CLI channel always passes a real config (`-c config/default.yaml`) and is
unchanged. See `src/ol_mcp/gates.py` and `docs/API.md` § 2.1–2.2.

## FAKE_LLM decision matrix

`OMNI_TEST_FAKE_LLM=1` enables mock translation (no API calls).
Use this table to decide when to set it:

| Scenario | Set `OMNI_TEST_FAKE_LLM=1`? | Why |
|----------|---------------------------|-----|
| Running unit tests | **YES** | Required. All pipeline tests use `_FakeModelPool`. |
| Running E2E tests with FAKE_LLM | **YES** | Validates pipeline orchestration without API cost. |
| Running E2E tests with real LLM | NO | Set real API keys, ensure `OMNI_TEST_FAKE_LLM` is UNSET. |
| Debugging translation quality | NO | Need real LLM responses to evaluate output. |
| Config validation / env var check | **YES** | Bypasses `${VAR}` resolution errors during `_check_env_vars()`. |
| MCP server testing | **YES** | Zero-cost smoke testing of MCP tools. |
| CI (pull request) | **YES** | Required. Prevents API key leakage in CI logs. |
| CI (nightly regression) | NO | Nightly runs test against real LLMs. |
| Production deployment | NO | Real translation requires real LLM calls. |
| Development / iteration | **YES** | Avoid burning through API quota during active development. |

**Decision flow:**

1. Are you running in CI on a PR? → **YES** (no API keys in CI)
2. Are you just testing the pipeline orchestration? → **YES** (no need to call real LLMs)
3. Are you validating translation quality or running nightly tests? → **NO** (need real LLM output)
4. Unsure? → **YES** (safe default — set it unless you specifically need real translations)
