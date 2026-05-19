"""Tests for skill invocation via CLI."""
import json
import pytest
from pathlib import Path
from tests.skill_helpers import verify_cli_json_output, create_temp_input


class TestSkillInvocation:
    """Test CLI JSON output format and error handling."""

    def test_cli_json_output_format(self):
        """Verify --json flag produces valid JSON with required fields."""
        # Test with nonexistent file to get JSON error output
        cmd = [
            "python", "-m", "ol_cli",
            "translate-md", "nonexistent.md",
            "-o", "/tmp/out",
            "--json"
        ]
        result = verify_cli_json_output(cmd, ["success", "error"])

        # Should return result (may fail, but should be valid JSON structure)
        assert "success" in result, "Missing 'success' in result"
        assert "error" in result or result.get("json"), "Missing 'error' or 'json' in result"

    def test_cli_json_error_format(self):
        """Verify error JSON has proper structure."""
        cmd = [
            "python", "-m", "ol_cli",
            "translate-md", "nonexistent.md",
            "-o", "/tmp/out",
            "--json"
        ]
        result = verify_cli_json_output(cmd, ["success", "error"])

        # Even on error, should have proper JSON structure
        if result.get("error") is None and result.get("json"):
            data = result["json"]
            assert "success" in data
            assert data["success"] is False or "error" in data

    def test_cli_help_shows_json_flag(self):
        """Verify --json flag appears in help output."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "ol_cli", "translate-md", "--help"],
            capture_output=True,
            text=True,
        )
        assert "--json" in result.stdout, "--json flag not in help"

    def test_temp_input_creation(self):
        """Verify create_temp_input helper works."""
        text = "# Test\n\nHello world."
        path = create_temp_input(text)

        try:
            assert path.exists()
            assert path.suffix == ".md"
            content = path.read_text()
            assert "Hello world" in content
        finally:
            path.unlink(missing_ok=True)