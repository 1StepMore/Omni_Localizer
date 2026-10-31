# OL LLM model pool + env vars (moved from AGENTS.md, #162)

## Model pool

OL is configured via `config/default.yaml` + `config/local.yaml`.
Each model has:
- `provider` (e.g., `openai`)
- `model` (e.g., `glm-4.7-flash`)
- `priority` (1 = highest)
- `role` (`translation` | `judging` | `restoration` | `profiling`)
- `api_key` (use `${ENV_VAR}` syntax)
- `base_url` (for non-OpenAI providers)
- `timeout` (per-request, default 120s)
- `requests_per_minute` (default 500) — routing weight only, NOT hard-enforced (E5E-83 removed `enforce_model_rate_limits`)
- `max_parallel_requests` (default unset) — enforced cap on simultaneous in-flight requests; use it when the provider 429s on concurrency (AMD `model_concurrency_rate_limit_exceeded`, Zhipu `code 1305`)

**Unified pool (canonical)** — `config/default.yaml` is the committed source of
truth (2 tiers × 4 roles); `ol init` writes `config/local.yaml`. `local.yaml` is
a **gitignored operator override**, not a byte-for-byte mirror: it may legitimately
differ in tier count, rate limits, and timeouts (the operator config on this
machine adds a third free `stealth/cat-jam:free` tier per role, keyed by
`OL_COMMANDCODE_API_KEY`).

- **DeepSeek-V4.1-Flash** → AMD Radeon (`AMD_API_KEY`, `https://developer.amd.com.cn/radeon/api/v1`) — priority-1 primary for translation/judging/restoration/profiling
- **glm-4.7-flash** → Zhipu (`ZHIPU_API_KEY`, `https://open.bigmodel.cn/api/paas/v4`) — priority-2 fallback

Every `api_key`/`base_url` is a `${ENV_VAR}` reference; literal keys are
never written. Each of `translation`, `judging`, and `restoration` must
have **≥2 models** — `ol doctor` enforces this as one of its 5 checks.

litellm Router with `routing_strategy="simple-shuffle"` and
`num_retries=2` picks a model within the role group. If it fails,
the next model in priority is tried.

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMNI_TEST_FAKE_LLM=1` | unset | **Required** for tests. Mock LLM responses with the `_FakeModelPool` seam. |
| `OMNI_RUN_REAL_LLM=1` | unset | **Escape hatch — skips the API-key pre-check** (`precheck_api_keys`) that guards `ol translate-md` / `ol translate-xliff`. It does **not** enable real LLM calls (those are the default; `OMNI_TEST_FAKE_LLM=1` disables them) — the name is misleading: it bypasses a fail-fast check, it does not switch on network calls. Home: `docs/real_llm_runbook.md`. |
| `OL_CONFIG_PATH` | `config/default.yaml` | Config file path override. |
| `AMD_API_KEY` / `ZHIPU_API_KEY` | (none) | LLM provider API keys (DeepSeek-V4.1-Flash / glm-4.7-flash). |
| `OL_COMMANDCODE_API_KEY` | (none) | Key for the optional third tier (`stealth/cat-jam:free`) in an operator's gitignored `config/local.yaml`. |
| `OMNI_CACHE_DIR` | `~/.omni_cache` | Cache root; OL stores content-addressed entries under `<root>/ol/`. Read at call-time. |
| `OMNI_LOG_FORMAT` | `console` | `json` for structured logs. |
| `OPP_LOG_LEVEL` | `INFO` | Log level. |
| `OL_MAX_INPUT_SIZE_MB` | 50 | Reject CLI inputs larger than this. |
| `OL_LENGTH_RATIO_MIN` | 0.5 | Minimum acceptable translated/source length ratio (quality gates). |
| `OL_LENGTH_RATIO_MAX` | 3.0 | Maximum acceptable translated/source length ratio (quality gates). |
| `OL_TARGET_LOCALE` | (unset) | Target locale override for locale-specific quality gates (e.g. `en-US`, `en-GB`, `fr-FR`). Falls back to `locale.target_locale` in config. |
| `MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`) | (none) | **REQUIRED for the MCP server** (`ol-mcp`). Comma-separated allowlist of directories the MCP may read/write. **Fail-CLOSED:** if all of `MCP_ALLOWED_DIRECTORIES` / `OL_MCP_ALLOWED_DIRS` / `OL_ALLOWED_DIRECTORIES` are unset, `get_default_validator()` raises `MCPNotConfiguredError` (error code `OL_MCP_NOT_CONFIGURED`; a `ValueError` subclass) — the server refuses to serve (no silent `cwd` + `/tmp` default). The MCP error envelope reports `OL_MCP_NOT_CONFIGURED` with recovery strategy `configure_environment`, NOT `OL_INVALID_INPUT`/`fix_input`. `OL_ALLOWED_DIRECTORIES` is a deprecated fallback. |
| `${VAR}` patterns in config | Per-provider | Env var references in `config/default.yaml` using `${VAR}` syntax. **Two-layer behavior:** (1) `schema.py:_check_env_vars()` WARNS at startup if a `${VAR}` is unset; (2) `router.py:_resolve_env_vars()` **raises `ValueError`** at runtime if a model with an unset var is actually invoked. Set `OMNI_TEST_FAKE_LLM=1` to bypass for testing. Only set env vars for providers you use. **BYOK gate is OR, not AND:** the CLI pre-check passes when **at least one** referenced provider key is set — you do not need every provider. With **zero** keys it still fails closed, and the error distinguishes "no provider key configured at all" from "keys configured but none referenced by this pool". `ol doctor`'s env check mirrors the router's real rule: the pool is usable when **every role has at least one usable model**. |

The MCP server is configured separately in `src/ol_mcp/config.py` —
OL's MCP server is `ol-mcp` (no `-server` suffix, **different** from
OPP's `opp-mcp-server` and ORF's `orf-mcp-server`). Startup additionally
requires `MCP_ALLOWED_DIRECTORIES` (fail-CLOSED; see the env-var table
above and `src/ol_mcp/security.py:get_default_validator`). When the
allowlist is missing, any tool call that builds a validator returns
`success=false` with `error.code == "OL_MCP_NOT_CONFIGURED"` and recovery
strategy `configure_environment` — set the env var, do not change the
request input.
