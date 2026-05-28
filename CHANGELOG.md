# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-05-28

### Added
- **`translate_xliff` MCP tool**: New tool for translating XLIFF files through shield → translate → repair → unshield pipeline
  - Preserves XLIFF inline elements (x, bx, ex, mrk, ph, alayout, g, ign tags) automatically
  - Uses `XliffParser`, `XliffShield`, `XLIFFRepairPipeline`, and `ModelPool` infrastructure
  - Supports `output_path` parameter — `None` = overwrite source with warning
  - Returns `{"success", "output_path", "units_processed", "warnings"}`

### Changed
- **`batch_translate_texts` assembled_document**: Return now includes `assembled_document` field joining all translated texts with `---` separator for seamless chunk reassembly

## [0.3.0] - 2026-05-25

### Added
- **MCP Server** (`src/ol_mcp/`): New package providing text-in/text-out MCP tools for agent-native localization without file I/O. 6 tools: `translate_md_text`, `judge_text`, `load_glossary`, `get_relevant_terms`, `search_tm`, `batch_translate_texts`.
- **MCP entry point** (`ol-mcp`) via `pip install -e ".[mcp]"`. Server uses stdio transport.
- **`mcp>=1.0.0`** added as optional dependency.
- **Hermes SKILL.md** updated with MCP Tools section documenting the agent-friendly interface.

### Changed
- SKILL.md now recommends MCP interface over CLI for pipeline/chapter-by-chapter use cases.

### Fixed
- `_load_env_file()` was defined but never called, causing `.env` files to be completely ignored. API keys set via `.env` would fail validation with "environment variable not set". Now `_load_env_file()` is called at the start of `load_config()` before config validation.

## [0.2.8] - 2026-05-24

### Fixed
- `_build_fallbacks()` used model ID ("openai/gpt-4o-mini") as fallback key, but litellm Router looks up by model_name (role: "translation"). Now uses role as key, so fallback lookup succeeds.

## [0.2.7] - 2026-05-24

### Fixed
- `ModelPool` fallback mechanism was completely broken: `fallbacks=[]` was never passed to litellm Router, so priority 2/3 models were never used as failovers. Now `_build_fallbacks()` correctly constructs per-role fallback chains based on priority ordering.
- `timeout=30` hardcoded in Router init overrode per-model `timeout` config. Now uses the maximum timeout across all configured models (default 180s).

### Changed
- `ModelPool` now passes `fallbacks=` and dynamic `timeout=` to litellm Router on initialization.

## [0.2.6] - 2026-05-24

### Changed
- `publish.yml` now tracks PyPI deployment in GitHub Deployments page

## [0.2.4] - 2026-05-23

### Fixed
- `_translate_md_async` and `translate_batch` now use `ModelPool()` default when `--config` not provided (previously crashed with `TypeError: path must not be None`)

## [0.2.5] - 2026-05-24

### Changed
- `LLMModelConfig.timeout` is now configurable per model (default: 60s, previously hardcoded 30s in Router)

## [0.2.3] - 2026-05-23

### Fixed
- TMService lock file handle leak: `_save()` now uses proper context manager for file locking
- Duplicate `FormatNotSupportedError` removed from `ol_buses/format_guard.py`, now imports from `ol_core.exceptions`
- `validate_config()` now performs actual validation instead of always returning True
- Added missing `Any` type import to `ol_batch/processor.py`
- Moved 8 regex patterns to module-level constants in `ol_md/shield.py` for performance
- Removed empty `test_ensemble_uses_median_aggregation` test stub
- `_generate_frontmatter()` now uses `_get_ol_version()` instead of hardcoded `"0.2.0"`
- `translate-batch` documentation added to OpenCode and Hermes SKILL.md files
- `config/test_universal.yaml` now uses OpenAI instead of MINIMAX/BAIDU for translation provider

### Added
- Content-level language detection with `--detect-language` flag for `translate-batch` (enabled by default)
- When content is detected as already being in the target language, `translate-batch` skips translation and copies the original file with `skipped: true` frontmatter metadata

### Changed
- Test assertions updated to match actual `ModelPool` defaults (`num_retries=2`, `timeout=30`)
- `pyproject.toml` litellm dependency lowered to `>=1.82.0` for broader compatibility

## [0.2.2] - 2026-05-22

### Fixed
- XLIFF nested same-type inline elements (mrk, em) now handled correctly with stack-based matching
- L4 repair fallback now appends original tag content, not placeholder markers
- L1 regex now processes all matches (count=0 instead of count=1)
- JudgeService mock score heuristic now fully documented
- ScorerService now uses sacrebleu for real BLEU scoring
- COMETService MQM error spans now stored in EvaluationResult for future analysis
- is_complete() now supports optional strict mode for content verification
- g and ign XLIFF inline tags now properly shielded

### Changed
- Added sacrebleu>=2.0 dependency for BLEU scoring

## [0.2.1] - 2026-05-22

### Fixed
- Version number inconsistency (ol_cli.py, tests, README now all use 0.2.0)
- Environment variable resolution now fails fast instead of using literal placeholder values
- Added env var validation to LLMModelConfig schema (calls _check_env_vars)
- Removed .env loading at module import time (side effect)
- Removed duplicate QueueTimeoutError class, now uses ol_concurrency.scheduler
- Added logging to silent exception handlers in level3 repair and TM service

### Changed
- CI now runs ruff and mypy in separate lint job
- CI no longer silences test failures or security audit failures with `|| true`
- Restoration pool in default.yaml now uses different model (claude-3-haiku) for actual failover
- Config test_universal.yaml now correctly uses minimax/baidu providers instead of openai

### Security
- Environment variable resolution now raises ValueError if referenced env var is not set

## [0.2.0] - 2025-01-20

### Added
- YAML frontmatter support for markdown translation output
- XLIFF header note support for translation metadata
- `--frontmatter` (default) / `--no-frontmatter` CLI options for batch and single file translation
- OpenCode and Hermes skill documentation updated

## [0.1.0] - 2025-01-01

### Added
- Initial release
- Translate markdown files using LLM APIs
- Translate XLIFF files using LLM APIs
- Model pool failover with LiteLLM router
- Content shielding for code blocks, links, images
- 4-layer semantic repair pipeline
- LLM-based translation quality judging
- Translation memory integration via hypomnema
- Span alignment for content preservation
- Agent skill support for OpenCode and Hermes
- JSON output mode for machine-readable results