---
name: ol-localizer
description: Translate Markdown documents between languages using AI-powered localization with quality control. Handles code blocks, links, and technical content preservation.
compatibility: hermes
---

# Omni-Localizer

## When to Use
Use this skill when you need to translate Markdown documents between languages. Examples:
- Translating documentation from English to Chinese/Japanese/etc.
- Localizing user-facing content for different markets
- Converting technical docs to multiple languages

## Procedure

### translate-md (Single File)
1. Write the source text to a temporary `.md` file
2. Invoke the CLI:
   ```
   python -m ol_cli translate-md <file.md> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir> --json
   ```
3. Parse the JSON output for success/error status
4. If successful, read the translated file from `<output_dir>/<original_filename>`

### translate-batch (Directory)
1. Prepare a directory containing markdown files to translate
2. Invoke the CLI:
   ```
   python -m ol_cli translate-batch <directory> -c config/default.yaml -s en -t zh -o output/ --json
   ```
3. Parse the JSON output for success/error status per file
4. If successful, read translated files from `<output_dir>`

### translate-xliff (Layout-Preserving Path)

Use when you have an XLIFF file from OPP (with skeleton.zip) and need
the output to preserve the original document layout:

1. Ensure the XLIFF file and skeleton.zip are in the same directory
   (OPP produces them together)
2. Invoke the CLI:
   ```
   ol translate-xliff <file.xlf> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir>
   ```
   Add `--polish` to run a post-translation pass that detects and
   fixes source-language residual (untranslated source text — OL#53):
   ```
   ol translate-xliff <file.xlf> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir> --polish
   ```
3. The output XLIFF has `<target>` elements filled and is ready for
   ORF's `apply-xliff` command

Truncation detection (OL#54): If the LLM response is truncated (ends
mid-sentence), OL reports it. In MD output, the warning appears as
`<!-- OL_WARN:truncation:... -->`. In XLIFF output, it appears as
`<note from="OL">Truncation detected...</note>`.

### Choosing translate-md vs translate-xliff

| Use translate-md... | Use translate-xliff... |
|---------------------|----------------------|
| For text-focused output | For layout-preserving output |
| When you want 16 output format options | When you need exact original layout |
| When you don't have a skeleton.zip | When OPP extracted with --target-format xlf/both |
| For web content, docs, e-books | For contracts, branded documents |

See the full decision tree in [OL AGENTS.md](https://github.com/1StepMore/Omni_Localizer/blob/main/AGENTS.md)
and the suite-level [Pipeline Selection Strategy](https://github.com/1StepMore/Omni_Suite/blob/main/README.md#pipeline-selection-strategy).

## Quality Gates

After translation, OL runs 4 config-driven quality gates that may embed
warnings in the output. Gates are non-blocking — they do not stop the
translation, but they flag potential issues for review.

| Gate | What it checks | Warning prefix | Env var override |
|------|---------------|----------------|------------------|
| `inline_tags` | `<bx>`, `<ex>`, `<x>` tag parity between source and target | `OL_WARN: INLINE_TAG_MISMATCH` | — |
| `terminology` | Mixed source term + glossary translation in target | `OL_WARN: TERMINOLOGY_INCONSISTENCY` | — |
| `length_ratio` | Translated/source length ratio out of bounds | `OL_WARN: LENGTH_RATIO` | `OL_LENGTH_RATIO_MIN` (default 0.5), `OL_LENGTH_RATIO_MAX` (default 3.0) |
| `locale` | Currency mixing, CJK date leakage, digit grouping (EU vs US), GB/US spelling | `OL_WARN: CURRENCY_MIXING`, `DATE_LEAKAGE`, `DIGIT_GROUPING`, `UNIT_SPELLING` | `OL_TARGET_LOCALE` (e.g. `en-US`, `en-GB`) |

When a gate fires, the warning is embedded directly in the output:

- **MD output**: `<!-- OL_WARN: CODE: message -->` HTML comment
- **XLIFF output**: `<note from="OL">CODE: message</note>` element

Gate defaults live in `config/default.yaml` under the `quality_gates:`
key. Set `OMNI_TEST_FAKE_LLM=1` to test the pipeline without real LLM
calls.

## Configuration

OL supports multiple LLM providers. Set only the keys for providers
you use:

Required (at least one):
- `ZHIPU_API_KEY` - API key for Zhipu AI (glm-4-flash)
- `AGNES_API_KEY` - API key for Agnes AI (agnes-2.0-flash)
- `NVIDIA_NIM_API_KEY` - API key for NVIDIA NIM (deepseek-ai/deepseek-v4-flash, moonshotai/kimi-k2.6)
- `OPENCODE_GO_KEY` - API key for OpenCode Go (deepseek-v4-flash)
- `OPENCODE_GO_BASE_URL` - Base URL for OpenCode Go provider

Quality gate overrides (optional):
- `OL_LENGTH_RATIO_MIN` - Minimum acceptable translated/source length ratio (default: 0.5)
- `OL_LENGTH_RATIO_MAX` - Maximum acceptable translated/source length ratio (default: 3.0)
- `OL_TARGET_LOCALE` - Target locale for locale-specific quality rules

Testing:
- `OMNI_TEST_FAKE_LLM=1` - Bypass real LLM calls (use mock responses)

## Pitfalls
- **API keys not set**: Ensure at least one provider API key is set
  (`ZHIPU_API_KEY`, `AGNES_API_KEY`, `NVIDIA_NIM_API_KEY`, or `OPENCODE_GO_KEY`)
- **Check output warnings**: After translation, scan for `OL_WARN:` comments
  (MD) or `<note from="OL">` elements (XLIFF) — these indicate quality gates
  fired and may signal residual source text, truncation, or length anomalies
- **Input file too large**: Recommend files under 100KB for optimal performance
- **Rate limiting**: If seeing rate limit errors, add retry with exponential backoff
- **Supported formats**: Both Markdown (.md) and XLIFF (.xlf, .xliff) are supported.
  For XLIFF, ensure the `.xlf` file has a companion `skeleton.zip` from OPP for
  layout-preserving round-trip

## Verification
1. Check JSON output has `"success": true`
2. Verify translated file exists in output directory
3. Confirm original formatting (code blocks, links) preserved