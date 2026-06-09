# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-06-09

### Changed
- **`ol_cli.py`**: Replaced all `: Any` type annotations (21 instances) and `-> Any` return types (4 instances) with concrete types
  - Added `TYPE_CHECKING` imports for `JudgeService`, `ModelPool`, `RetryManager`, `Glossary`
  - Added `from ol_core.dataclass import TranslationUnit` at top level
  - Used `typing.cast` for duck-typed seams (`_FakeModelPool`)
  - Zero new LSP diagnostics — only pre-existing errors remain

## [0.4.0] - 2026-06-03

### Added
- **LQA auto-invoke in CLI**: `_translate_md_async` and `_translate_xliff_async` in `ol_cli` now wrap `pool.translate` in a `RetryManager` with `JudgeService` when `config.enable_lqa` is true
  - Judges the translation result against the source; if the score falls below `lqa_threshold`, the translation is retried up to `lqa_max_retries` times
  - Opt-in via config flags; existing tests and configs are unchanged
- **LQA config fields** in `ProjectConfig` (`ol_config/schema.py`):
  - `enable_lqa: bool = False` — master switch for LQA auto-invoke
  - `lqa_threshold: float = 7.0` — minimum acceptable quality score (1-10)
  - `lqa_max_retries: int = 2` — max retry attempts when score is below threshold
- **`_escape_xml_entities()` helper** in `src/ol_buses/xliff_bus.py` for sanitizing LLM-produced XLIFF target text
  - Escapes `&`, `<`, `>`, `"`, and `'` before placeholders are restored into the `<target>` element
- **`.gitignore`**: ignore `config/local.yaml`, `config/local.*.yaml`, `config/secret.yaml`, and `config/production.yaml` so real LLM config files are never committed

### Fixed
- **Real-LLM nightly test was failing with `lxml.etree.XMLSyntaxError: xmlParseEntityRef: no name`**: LLM-produced XLIFF target text occasionally contains unescaped `&` (e.g., `R&D`, `AT&T`) which broke XML serialization on round-trip
  - Fix: `write_target_back()` now applies `_escape_xml_entities()` to the LLM target text **before** restoring placeholders, so `&` becomes `&amp;` and `lxml` can reparse the file
  - Unblocks the real-LLM nightly test (Test 3 LQA judge path)

## [0.3.4] - 2026-05-29

### Fixed
- **`translate_xliff` double-shielding bug**: Removed redundant `shield_xliff()` call that was overwriting the shield map from parsing
  - `XliffParser.parse()` already calls `extract_inline_elements()` which shields tags and populates `unit.shield_map`
  - Calling `shield_xliff(unit.source_text)` again found no tags (already shielded) → empty shield map → `{{_OL_XTAG_*}}` placeholders not restored
  - Fix: use `unit.shield_map` directly from parsing instead of re-shielding
- **`write_target_back()` missing restore_tags call**: `unit.target_text` now passed through `restore_tags()` before writing
  - Without this call, `{{_OL_XTAG_*}}` placeholders from translation leak into final XLIFF output
  - Fix: call `restore_tags(unit.target_text, unit.shield_map)` on line 138 of xliff_bus.py
- **`translate_xliff` MCP tool bypass fix**: MCP tool now also calls `_ensure_target_tags()` before creating TranslationContext
  - MCP tool was directly reading XLIFF file without target injection, bypassing `load_xliff()`
  - Fixed by applying `_ensure_target_tags()` to `original_text` in MCP tool path
- **`translate_xliff` MCP output_path default**: When `output_path=None` (default), now generates `input_translated.xlf` instead of overwriting source file
  - Fix: use `Path.with_stem(f"{input_p.stem}_translated")` to create output filename
- **`ModelPool` OOM prevention**: Changed `ModelPool` to singleton pattern via `get_instance()` to prevent creating new litellm Router per MCP call
  - `ModelPool.__init__` now raises `NotImplementedError`
  - `ModelPool.get_instance(config_path)` returns cached instance per config path
  - Updated all callers: MCP tools, CLI commands, repair pipelines

### Investigation
- **Bug #MD-01: `translate_md_text` silent failure** (under investigation)
  - Added logging to `_translate_single()` for exception tracing
  - Added fallback to `type(e).__name__` when `str(e)` is empty
  - `_translate_single` now has try/except to ensure exceptions propagate with context
  - Root cause not yet confirmed - may be litellm or pydantic edge case

## [0.3.3] - 2026-05-28

### Fixed
- **`write_target_back()` target injection**: `load_xliff()` now pre-injects empty `<target></target>` tags for OPP-generated XLIFF files
  - OPP XLIFF only contains `<source>` elements without `<target>`
  - `write_target_back()` regex requires `<target>...</target>` to exist for replacement
  - Added `_ensure_target_tags()` helper to inject targets before creating TranslationContext
  - `write_target_back()` now reads from `ctx.original_full_text` (which has targets injected)

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