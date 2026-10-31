# OL CLI reference (moved from AGENTS.md, #162)

| Command | Purpose |
|---------|---------|
| `ol translate-md <file> -s <src> -t <tgt> -o <dir>` | Translate a single MD file |
| `ol translate-md <file> -s en -t zh --chunk-by-paragraph` | Translate paragraph-by-paragraph (better for literary text) |
| `ol translate-md <file> --no-glossary --no-restoration` | Disable optional stages |
| `ol translate-xliff <file> -s <src> -t <tgt>` | Translate an XLIFF file |
| `ol translate-batch <dir> -s <src> -t <tgt> --concurrency 10` | Batch translate a directory |
| `ol extract-warnings <file>` | Extract placeholder restoration warnings from an output |
| `ol init [--config -c PATH] [--non-interactive] [--force]` | Interactive wizard generating `config/local.yaml` with the unified model pool |
| `ol doctor [--config -c PATH] [--json]` | Validate model-pool config (5 checks) and print a pass/fail checklist; the env check passes when every role has at least one usable (keyed) model |
| `ol-mcp` | Start the MCP server (stdio) |

## Common flags

- `--config <path>` — path to YAML config (default `config/default.yaml`)
- `--json` — emit a one-line JSON status/summary (for agent parsing)
- `--glossary <path>` — glossary JSON file (overrides config)
- `--no-glossary` — disable glossary injection even if config has one
- `--glossary-max-terms <N>` — top-N terms to inject per unit (default `5`)
- `--chunk-by-paragraph` — split by blank lines, translate each separately
- `--styleguide <path>` — inject a StyleGuide JSON (output of `profile-doc`)
- `--polish` — post-translation cross-unit consistency pass
- `--scorer <bleu|comet|none>` — LQA scorer backend
- `--report-coverage` / `--coverage-threshold <pct>` — glossary coverage report + warning threshold
- `--images-json <path>` — copy an OPP `images.json` alongside the output
- `--concurrency <N>` — max concurrent translations
- `--no-cache` — bypass the content-addressed cache and force a fresh translation
- `--clear-cache` — remove all cached OL outputs and exit
- `--fail-on-untranslated` — exit `1` if any unit came back untranslated
- `--no-frontmatter` — skip YAML frontmatter injection
- `--no-restoration` — skip post-translate placeholder restoration (Level 3 LLM)
- `--log-format console|json` — log output format
