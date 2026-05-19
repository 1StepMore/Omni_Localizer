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
1. Write the source text to a temporary `.md` file
2. Invoke the CLI:
   ```
   python -m ol_cli translate-md <file.md> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir> --json
   ```
3. Parse the JSON output for success/error status
4. If successful, read the translated file from `<output_dir>/<original_filename>`

## Configuration
Required environment variables:
- `MINIMAX_API_KEY` - API key for MiniMax translation service
- `BAIDU_API_KEY` - API key for Baidu ERNIE translation service (backup)

Optional environment variables:
- `MINIMAX_BASE_URL` - Custom endpoint for MiniMax API
- `BAIDU_BASE_URL` - Custom endpoint for Baidu API

## Pitfalls
- **API keys not set**: Ensure MINIMAX_API_KEY and BAIDU_API_KEY are in environment before invoking
- **Input file too large**: Recommend files under 100KB for optimal performance
- **Rate limiting**: If seeing rate limit errors, add retry with exponential backoff
- **Unsupported format**: Only Markdown (.md) is supported in v1 - not XLIFF or other formats

## Verification
1. Check JSON output has `"success": true`
2. Verify translated file exists in output directory
3. Confirm original formatting (code blocks, links) preserved