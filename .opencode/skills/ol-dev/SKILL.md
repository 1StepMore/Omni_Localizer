---
name: ol-dev
description: Develop inside the OL sub-repo — add a translation channel/mode, extend the quality-gate set, wire a new MCP tool, or touch the model-pool routing. Use when asked to 加翻译通道/模式、加质量门、改 OL MCP 工具、或动模型池路由。
---

# OL dev — channels, gates, and MCP surface

Checklist-driven SOP. `scripts/coverage_matrix.py --check` and
`scripts/doc_inventory.py --check` enforce the numbers/paths — run both
before pushing.

## Adding a quality gate (the most common OL change)

1. **Gate function**: `src/ol_lqa/quality_gates.py` — implement
   `gate_<n>_<name>(source, target, …) -> list[str]` returning
   `OL_WARN: <CODE>` strings; the gate must never raise past its own
   try/except wrapper (one gate failing must not block the others).
2. **Wire it into `run_quality_gates`**: add an `<name>_enabled: bool`
   keyword parameter — the doc gate derives the "8 quality gates" count
   from these `*_enabled` params, so the count updates itself.
3. **Config**: add the toggle to the `quality_gates:` config schema
   (`ol_config/schema.py`) with the same default as the function.
4. **Docs**: add a row to the gate table in `docs/dev/gotchas.md`
   (description + warning codes) and a row in
   `docs/dev/production-matrix.md` (with a ✅/⚠️ mark); update the gate
   diagram in `docs/dev/pipeline.md`.
5. **Tests**: `tests/test_quality_gates.py`-style regression with a
   minimal triggering fixture.

## Adding a translation channel or mode

1. **CLI**: sub-command module under `src/cli/` + registration in
   `ol_cli.py`; shared plumbing (`ExitCode`, `precheck_api_keys`) comes
   from `src/cli/_shared.py`.
2. **MCP**: a tool entry in `src/ol_mcp/tools.py` (`TOOL_REGISTRY` —
   the doc gate derives "21 MCP tools" from it) + Pydantic input model.
3. **Env/config**: prefer `OL_*` env vars documented in
   `docs/dev/llm-pool.md`; fail-closed semantics only for the MCP
   allowlist (that invariant must not leak into CLI flags).
4. **Docs**: channel row in `docs/dev/production-matrix.md` +
   channel-selection note in `docs/dev/pipeline.md`.
5. **Scenarios + gates**: in-repo `scenarios/` (tier 2 needs real keys;
   `unconfigured` without them is honest) + the two --check gates.

## Extending the model pool routing

`src/ol_pool/router.py` wraps litellm Router. Pool schema lives in
`ol_config/schema.py` (`LLMPoolConfig`). Every `api_key`/`base_url` is a
`${ENV_VAR}` reference — literal keys are never written. Role semantics
(`translation`/`judging`/`restoration`/`profiling`) and the
`*_enabled`-style knobs are documented in `docs/dev/llm-pool.md`;
`ol doctor`'s five checks must keep passing on the shipped
`config/default.yaml`.

## Gates to run before pushing

```bash
make test                                  # full unit suite (OMNI_TEST_FAKE_LLM=1)
ruff check src/ tests/                     # OL's own lint gate
python scripts/coverage_matrix.py --check  # production matrix truth
python scripts/doc_inventory.py --check    # doc truth
```
