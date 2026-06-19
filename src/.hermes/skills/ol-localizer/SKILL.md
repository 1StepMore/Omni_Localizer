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