# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `--frontmatter` / `--no-frontmatter` CLI options for batch and single file translation
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