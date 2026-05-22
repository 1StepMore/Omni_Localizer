"""OL_WARN extraction tool for generating review files."""

from pathlib import Path


def extract_warnings(input_file: str, output_file: str) -> None:
    """Extract segments containing OL_WARN patterns from input file.

    Supports three formats:
    - MD: <!-- OL_WARN: {message} -->
    - XLIFF: <note from="OL">{message}</note>
    - Plain text: OL_WARN: {message}

    Args:
        input_file: Path to source file (MD, XLIFF, or plain text)
        output_file: Path to output review file

    Read-only operation - does NOT modify source files.

    """
    import re

    input_path = Path(input_file)
    content = input_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=False)

    output_lines = []

    for line in lines:
        md_match = re.search(r'<!--\s*OL_WARN:\s*([^>]+)\s*-->', line)
        xliff_match = re.search(r'<note\s+from="OL"[^>]*>([^<]+)</note>', line)
        plain_match = re.search(r'OL_WARN:\s*(\w+)', line)

        if md_match or xliff_match or plain_match:
            output_lines.append(line)

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_lines:
        output_path.write_text('\n'.join(output_lines), encoding="utf-8")
    else:
        output_path.write_text('# No OL_WARN warnings found', encoding="utf-8")
