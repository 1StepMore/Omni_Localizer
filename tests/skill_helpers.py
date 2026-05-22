"""Test helpers for skill verification."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml


def verify_skill_discovery(skill_path: Path) -> bool:
    """Check if SKILL.md exists and has valid frontmatter.

    Args:
        skill_path: Path to skill directory (e.g., Path('src/.opencode/skills/ol-localizer'))

    Returns:
        True if SKILL.md exists and has valid YAML frontmatter

    """
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False

    try:
        content = skill_md.read_text()
        if not content.startswith('---'):
            return False

        parts = content.split('---')
        if len(parts) < 3:
            return False

        yaml.safe_load(parts[1])
        return True
    except Exception:
        return False


def verify_skill_frontmatter(skill_path: Path, required_fields: list[str]) -> bool:
    """Validate required YAML frontmatter fields.

    Args:
        skill_path: Path to skill directory
        required_fields: List of required field names (e.g., ['name', 'description'])

    Returns:
        True if all required fields present

    """
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False

    try:
        content = skill_md.read_text()
        parts = content.split('---')
        if len(parts) < 3:
            return False

        data = yaml.safe_load(parts[1])

        for field in required_fields:
            if field not in data:
                return False

        return True
    except Exception:
        return False


def verify_cli_json_output(command: list[str], expected_fields: list[str]) -> dict[str, Any]:
    """Run CLI command and verify JSON output.

    Args:
        command: CLI command as list (e.g., ['python', '-m', 'ol_cli', 'translate-md', ...])
        expected_fields: List of required JSON fields

    Returns:
        dict with keys: 'success' (bool), 'json' (parsed JSON or None), 'error' (str or None)

    """
    result = {
        'success': False,
        'json': None,
        'error': None,
    }

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = proc.stdout.strip()
        if not output:
            output = proc.stderr.strip()

        try:
            data = json.loads(output)
            result['json'] = data

            for field in expected_fields:
                if field not in data:
                    result['error'] = f"Missing field: {field}"
                    return result

            result['success'] = True
        except json.JSONDecodeError as e:
            result['error'] = f"JSON parse error: {e}"

    except subprocess.TimeoutExpired:
        result['error'] = "Command timed out"
    except Exception as e:
        result['error'] = str(e)

    return result


def create_temp_input(text: str, suffix: str = '.md') -> Path:
    """Create a temporary Markdown file for testing.

    Args:
        text: Content to write to temp file
        suffix: File suffix (default: .md)

    Returns:
        Path to temporary file (caller should delete)

    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
    except Exception:
        os.close(fd)
        raise

    return Path(path)
