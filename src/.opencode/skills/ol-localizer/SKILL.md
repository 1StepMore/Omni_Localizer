---
name: ol-localizer
description: Translate Markdown documents between languages using AI-powered localization with quality control. Handles code blocks, links, and technical content preservation.
compatibility: opencode
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
3. The output XLIFF has `<target>` elements filled and is ready for
   ORF's `apply-xliff` command

### Choosing translate-md vs translate-xliff

| Use translate-md... | Use translate-xliff... |
|---------------------|----------------------|
| For text-focused output | For layout-preserving output |
| When you want 16 output format options | When you need exact original layout |
| When you don't have a skeleton.zip | When OPP extracted with --target-format xlf/both |
| For web content, docs, e-books | For contracts, branded documents |

See the full decision tree in [OL AGENTS.md](https://github.com/1StepMore/Omni_Localizer/blob/main/AGENTS.md)
and the suite-level [Pipeline Selection Strategy](https://github.com/1StepMore/Omni_Suite/blob/main/README.md#pipeline-selection-strategy).

## Configuration
Required environment variables:
- `OPENAI_API_KEY` - API key for your LLM provider

Optional environment variables:
- `OPENAI_BASE_URL` - Custom endpoint for your LLM provider

## Pitfalls
- **API keys not set**: Ensure OPENAI_API_KEY is in environment before invoking
- **Input file too large**: Recommend files under 100KB for optimal performance
- **Rate limiting**: If seeing rate limit errors, add retry with exponential backoff
- **Supported formats**: Both Markdown (.md) and XLIFF (.xlf, .xliff) are supported

## Verification
1. Check JSON output has `"success": true`
2. Verify translated file exists in output directory
3. Confirm original formatting (code blocks, links) preserved