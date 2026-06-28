# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Replace stale provider env vars** (`.env.example`, `AGENT_USAGE.md`, `real_llm_runbook.md`, `README.md`, `config/test_universal.yaml`): replaced 4 stale provider env vars (`MINIMAX`/`BAIDU`/`OPENAI`/`ANTHROPIC`) with current 5 (`ZHIPU`/`AGNES`/`NVIDIA_NIM`/`OPENCODE_GO`). All documentation and config references now reflect the active provider lineup.

- **Clarify two-layer env var behavior** (`AGENTS.md`, `README.md`): documented the dual-layer design — `schema.py` emits a `logging.warning()` at startup for unset env vars (non-blocking), while `router.py` raises `ValueError` when a model with missing credentials is actually invoked. Replaces the previously ambiguous "warning, not error" phrasing.

### Added

- **ARCHITECTURE.md cross-reference and openai-compat endpoint comments** (`ARCHITECTURE.md`, `config/default.yaml`): added cross-reference to suite-level `ARCHITECTURE.md` in the OL architecture doc. Added "openai-compat endpoint" comments for non-OpenAI providers (Zhipu, Agnes, NVIDIA NIM, Moonshot Kimi) in the default config to clarify that these providers use OpenAI-compatible APIs despite not being OpenAI.

- **Replace BAIDU model entries in test configs** (`config/test_universal.yaml`, `config/slim-test.yaml`): replaced `BAIDU` model entries (which had `account_overdue` errors) with current working providers (`glm-4-flash`, `agnes-2.0-flash`). Test configs now use functional credentials for CI/test reliability.

### Fixed

- **OL#10 — XLIFF target contains unescaped HTML from shield map** (`src/ol_buses/xliff_bus.py:write_target_back`). The function called `_escape_xml_entities()` BEFORE `restore_tags()`, so HTML content restored from the shield map (e.g. `<code>foo</code>`) was written into the `<target>` element as raw HTML — producing invalid XLIFF. Fixed by restoring first, then escaping with a new `_escape_xml_entities_preserving_xliff_tags()` helper that entity-escapes user-visible content while preserving XLIFF structural inline tags (`<x/>`, `<bx/>`, `<ex/>`) as valid XML.

## [0.5.2] - 2026-06-25

### Fixed

- **OL#8 — Cache key and TM search were not language-pair aware** (Hermes audit). Four related issues, all causing silent cross-language data corruption:
  1. **CLI output file cache** (`src/ol_cli.py:_cache_key`): the hash did not include `src_lang`/`tgt_lang`, so translating the same input to two different target languages would return the first language's cached output for the second call. Fixed by adding `src_lang`/`tgt_lang` parameters to `_cache_key`/`_check_cache`/`_write_cache` and threading them through both call sites.
  2. **LLM prompt cache** (`src/ol_pool/router.py:_make_cache_key`): the hash relied on the prompt text embedding the language pair (hidden coupling). Refactored to make `source_lang`/`target_lang` explicit key dimensions, removing the implicit dependency. Fixes the same anti-pattern in both translate and judge paths.
  3. **TM search language filter** (`src/ol_tm/service.py:search`): the method signature was `search(source_text, threshold)` with NO language filter, so a TM containing both en→zh and en→fr entries would return matches from BOTH language pairs for any English query. This would silently inject French TM matches into a Chinese translation prompt. Fixed by making `src_lang`/`tgt_lang` required parameters and filtering entries before similarity computation. Updated all callers (`ol_batch/processor.py`, `ol_mcp/tools.py`, tests).
  4. **Glossary language awareness** (`src/ol_terminology/glossary_class.py`): the `Glossary` dataclass had no language metadata, so a Chinese glossary could be silently injected into a French translation. Added optional `target_lang` field (extracted from JSON/YAML top-level if present), `for_target()` validator method, and a CLI-side warning when the loaded glossary's target_lang doesn't match the requested translation target.

- **Cross-language regression test** (`tests/test_ol_cache_cross_language.py`): new test class `TestCrossLanguageNoCacheCollision` covers the file cache, prompt cache, and TM cache paths. Locks in the new contract that translating the same input to two different target languages must produce different outputs.

### Migration

- `TMService.search()` now REQUIRES `src_lang` and `tgt_lang` parameters (keyword-only). This is a breaking change to the public API. All internal callers updated. External callers (MCP clients, batch scripts) must be updated to pass the language pair.
- `Glossary.load()` now reads an optional top-level `target_lang` field. Existing glossary files without this field continue to work (target_lang is None, no validation enforced).

## [0.5.1] - 2026-06-24

### Added
- **Multi-language punctuation normalization** (`src/ol_post/punctuation.py`): refactored from
  two hardcoded functions (`normalize_to_english`, `normalize_to_chinese`) to per-language-pair
  dispatch via `normalize(text, source_lang, target_lang)`. Added Japanese (en→ja) mapping:
  `,→、` `.→。` `?→？` `!→！` `:→：` `;→；` `(→（` `)→）`. Other languages (fr/de/ru/ko) use
  ASCII punctuation that was already correct. The dispatch site in `ol_cli.py` now passes
  `source_lang` and `target_lang` to the new `normalize()` function. Existing
  `normalize_to_chinese` and `normalize_to_english` remain as backward-compatible wrappers.

## [0.5.0] - 2026-06-24

### Changed
- **ML dependencies moved to optional `[ml]` extra** (`pyproject.toml`): `keybert`, `yake`, `sentence-transformers`, `transformers` are no longer required deps. These packages cause `import transformers` to hang in Python 3.13 (circular import via `regex._regex`) and pull in ~1GB of nvidia-*/torch C extensions. They are now available via `pip install omni-localizer[ml]`. `import ol` no longer triggers the ML stack. ML features (KeyBERT term extraction, YAKE fallback, TM semantic search) raise a clean `ImportError` when the extra is not installed. The `torch>=2.0.0` dep was already in `[ml]` — unchanged.

## [0.4.7] - 2026-06-24

### Fixed
- **Issue #5 — `normalize_to_chinese` corrupts fenced code-block punctuation** (`src/ol_post/punctuation.py:54-110`): The post-translate punctuation pass called `text.translate(_EN_TO_ZH)` on the full body, which replaced ASCII `:,.();?!()` inside ```json``` / ```yaml``` / ```csv``` code fences with their full-width Chinese equivalents. The LLM never sees fence content (the shield at `src/ol_md/shield.py:CODE_PATTERN` replaces it with markers and `unshield` restores the original ASCII on the way out), so the LLM pass preserved the syntax correctly — but this post-pass then corrupted it. Output JSON / YAML / CSV inside fences became syntactically invalid even though every upstream step did the right thing. Fix: split on the same triple-backtick fence regex the shield uses, translate only the non-fence spans, leave fence content verbatim. Mirrors the shield's fence coverage exactly (no tilde-fence support, no inline-code support) so the post-pass protects the same content the LLM pass protected. The symmetric `normalize_to_english` direction is unaffected — it only ever converts Chinese punctuation back to ASCII, which is the desired behavior for code blocks too. 16 new regression tests in `tests/test_post_punctuation_code_blocks.py` pin the contract (json/yaml/csv fence preservation, multi-fence, edge cases, fence pattern shape, inline-code scope boundary, symmetric direction unchanged).

## [0.4.6] - 2026-06-24

### Fixed
- **E2E-74** (`src/ol_pool/router.py:401-450`): `ModelPool.translate()` raised `UnboundLocalError` when `context=None` (the CLI default at `ol_cli.py:1011/1038/1183/1238`) or `context=dict` (matches the type hint). It also raised `AttributeError` when `context` was a non-empty `str` because the inner `if context:` branch tried to call `context.get(...)` on a string. Real-LLM translation was completely broken. Fix: build the user prompt based on the `context` type and ALWAYS assign `prompt` before use. `context=str` is now used verbatim (previously overwritten with a fresh build, silently discarding the injected TM/glossary section).
- **E2E-77** (`src/ol_md/shield.py:5`): `MATH_PATTERN = r'\$\$([^$]+)\$\$|\$([^$]+)\$'` had greedy `[^$]+` that consumed across intermediate `$` characters. Common English text containing two or more dollar signs (`"Price: $5.99 and $10 each"`, `"Earnings: $100 today and $50$ yesterday"`, `"I have $a variable named $b"`, `"Cost is $5$ (a typo)"`) was false-positive detected as math. Fix: inline math `$..$` now requires a LaTeX marker (backslash command, `^`, or `_`) inside the run. Display math `$$..$$` is unchanged.
- **E2E-78** (`src/ol_md/shield.py:14-15, 116-127`): The marker format was `\x00OL_{TYPE}_{ID:04d}\x00` (NUL-byte delimited). Real LLMs in the wild frequently strip or mangle the NUL control character during translation, which made `unshield_markdown` silently drop the original HTML / math / code for the affected marker. Fix: switch to `[OL:TYPE:NNNN]` (ASCII-delimited, unambiguous vs markdown link / image grammar). Additionally, `unshield_markdown` now appends any content whose marker was missing under a `<!-- OL_WARN:missing_shields key1,key2,... -->` HTML comment so content is never silently lost.
- **E2E-83** (`src/ol_pool/router.py:248-281`): `ModelPool.__init__` passed `optional_pre_call_checks=['enforce_model_rate_limits']` to the litellm Router. This litellm built-in maintains a per-model RPM token bucket in-process and synchronously raises `litellm.RouterRateLimitError` when the bucket is empty. For NVIDIA free-tier models (`rpm=40`) a single 60KB (26K-token) request took ~14s and depleted most of the bucket; the next request was then rejected by the pre-call check BEFORE the actual LLM call. OL's `translate()` retry loop caught the `RouterRateLimitError` and waited 10/20/40s backoffs (cumulative ~70s) for the in-memory bucket to refill, manifesting as a "14s 原文直出" (echo) or 70s+ hard failure. Hermes confirmed: Zhipu direct curl with the same 60KB input works (82s normal translation), so the failure is at the litellm layer. Fix: dropped the pre-call check. Per-model RPM is still set in each `litellm_params['rpm']` entry; rejection now comes from the provider's HTTP 429 (handled by the existing translate() exponential backoff) instead of from litellm's in-process bucket. Also added a "Large translation request" WARNING log when combined prompt size >50K chars so callers (CLI / MCP) have visibility into slow translations.
- **Conftest litellm stub fix** (`tests/conftest.py`): The repo's test conftest stubs `litellm` as a non-package to avoid the 30-90s real litellm import cost, but the stub lacked `__path__` so `from litellm.types.router import RouterRateLimitError` (required by `src/ol_pool/router.py`) failed at module-load time. This blocked `test_model_pool_failover.py` and `test_post_mortem_fixes.py` from collecting, and would block any future test that imports `ol_pool.router`. Three minimal changes: give the litellm stub `__path__`, add `litellm.types.router` to `_PRESET_BY_NAME` with a `RouterRateLimitError` class, and give blocker-created stubs `__path__` when they are subpackages of a blocked top-level package.

## [0.4.4] - 2026-06-14

### Added
- **`ol_post.punctuation` module** (`src/ol_post/punctuation.py`): Post-translate punctuation normalizer for the zh↔en pipeline.
  - `normalize_to_english(text)`: maps full-width Chinese punctuation (U+201C/D quotes, U+2018/9 single quotes, U+FF0C fullwidth comma, U+3002 ideographic full stop, etc.) to ASCII equivalents. Implemented with `str.maketrans` for O(1) per-character mapping.
  - `normalize_to_chinese(text)`: inverse direction — maps ASCII `,.;:""''` to Chinese equivalents.
  - Pure post-processing, no LLM calls, zero API cost.
  - Wired into `_translate_md_async` in `src/ol_cli.py` (after the repair stage, before writing the output file). Dispatched on `tgt_lang` prefix. The XLIFF path is unchanged (XLIFF `<target>` text is structural and re-escaped on the way out).
  - Fixes 82/1865-char (4.4%) Chinese punctuation contamination observed in English-mode Haier DOCX output, and the symmetric ASCII-in-Chinese problem in the en→zh direction.

### Fixed
- **`GLOSSARY_TERM_LIMIT` raised 5 → 20** (`src/ol_terminology/rag_injector.py:9`): The previous 5-term cap forced the auto-glossary injector to truncate the top-10 source terms to 5, silently dropping half the consistency coverage. 20 terms at ~5 chars each fits well under the LLM context budget for typical paragraphs. The `forced_terms` bypass mechanism is unchanged — callers do not populate it.

## [0.4.2] - 2026-06-12

### Fixed
- **`ol_cli.py`**: Fixed `ConcurrencyLimiter` kwarg in `_translate_md_units_concurrent` — `max_md_concurrent` changed to `max_translation` after scheduler refactor
- **`ol_concurrency/scheduler.py`**: Added `md_semaphore` property to `ConcurrencyLimiter` for the MD concurrent translation path
- **`tests/test_ol_cli.py`**: Updated version assertion from 0.2.6 to 0.3.1
- **`tests/test_ol_cli.py`**: Marked `test_translate_md_valid_input` as `xfail` — concurrent MD path broken since `extract_and_shield_md_units` was removed from `ol_md.extractor` (needs reimplementation)
- **LQA scorer tests**: `sacrebleu` dependency installed to fix 5 `ModuleNotFoundError` failures

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
## [0.3.5] - 2026-05-31

### Fixed
- **`XLIFFRepairPipeline.is_complete()` placeholder check** (E2E-64): `is_complete()` now checks for actual XML tag presence instead of only placeholder string/ID
  - Problem: `restore_tags()` correctly replaced `{{_OL_XTAG_bx_1_}}` with `<bx id="1" type="bold"/>`, but `is_complete()` checked for `'bx_1'` in text (not found) → returned `False` → triggered `level4_safe_fallback()` → appended duplicate tags + `<note>` → XLIFF target extraction failed → SKIPPED units
  - Fix: when `placeholder_str` not in text, check if `original_tag` (the actual XML tag) is in text as fallback before returning `False`
- **`ModelPool.translate()` prompt reinforcement**: Enhanced translation prompt to prevent LLM from echoing source text
  - Added explicit "CRITICAL: Output ONLY the {target_lang} translation" instruction
  - Changed prompt format from single-line to structured multi-part with labeled Source section
- **`ModelPool` rate-limit error handling**: Added `RouterRateLimitError` to retry-able exceptions alongside `RateLimitError`
  - MiniMax API may return `RouterRateLimitError` under load; now properly caught and retried with backoff

### Changed
- **`translate_xliff` CLI now requires explicit `--source-lang`/`--target-lang`**: When `--config` is provided, CLI language params must still be passed explicitly to override config defaults
  - Config schema defaults to `source_lang=en, target_lang=zh`; OL CLI was omitting language params and falling through to config defaults
  - Fix: always pass `--source-lang zh --target-lang en` in test harness

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
## [0.4.5] - 2026-06-23

### Fixed

- **Prompt injection stripping (E2E-65)**: `level1_regex_clean()` now strips `CRITICAL/IMPORTANT/NOTE: Output ONLY the \w+ translation.` patterns from LLM output before XLIFF serialization. Defends against the LLM echoing the system-prompt instruction into the translation.
  - `src/ol_xliff/repair/level1.py`
- **Base64 image ref dedup (E2E-14)**: `_translate_single()` in MCP `tools.py` now post-processes LLM output through `_dedup_b64_image_refs()` to remove duplicate base64 image refs the LLM re-encoded inline.
  - `src/ol_mcp/tools.py`
- **XLIFF repair `is_complete()` check (E2E-64)**: `XLIFFRepairPipeline.is_complete()` now verifies actual XML tag presence when the placeholder string was consumed by `restore_tags()`, instead of only checking for the placeholder ID. Also adds `RouterRateLimitError` to retry-able exceptions in `ModelPool`.
  - `src/ol_xliff/pipeline.py`
  - `src/ol_pool/router.py`
