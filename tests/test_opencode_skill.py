"""Tests for OpenCode skill discovery."""
from pathlib import Path

import pytest

from tests.skill_helpers import (
    verify_skill_discovery,
    verify_skill_frontmatter,
)


class TestOpenCodeSkill:
    """Test OpenCode skill existence and structure."""

    @pytest.fixture
    def skill_path(self) -> Path:
        return Path(__file__).parent.parent / "src" / ".opencode" / "skills" / "ol-localizer"

    def test_opencode_skill_exists(self, skill_path: Path):
        """Verify OpenCode skill directory and SKILL.md exist."""
        assert skill_path.exists(), f"Skill path {skill_path} does not exist"
        assert (skill_path / "SKILL.md").exists(), "SKILL.md not found"

    def test_opencode_skill_frontmatter_valid(self, skill_path: Path):
        """Verify SKILL.md has valid YAML frontmatter."""
        assert verify_skill_discovery(skill_path), "SKILL.md frontmatter invalid"

    def test_opencode_skill_required_fields(self, skill_path: Path):
        """Verify SKILL.md has required frontmatter fields."""
        required = ["name", "description"]
        assert verify_skill_frontmatter(skill_path, required), "Missing required field"

    def test_opencode_skill_has_procedure(self, skill_path: Path):
        """Verify SKILL.md contains Procedure section."""
        content = (skill_path / "SKILL.md").read_text()
        assert "Procedure" in content, "Missing Procedure section"

    def test_opencode_skill_has_pitfalls(self, skill_path: Path):
        """Verify SKILL.md contains Pitfalls section."""
        content = (skill_path / "SKILL.md").read_text()
        assert "Pitfalls" in content, "Missing Pitfalls section"

    def test_opencode_skill_has_verification(self, skill_path: Path):
        """Verify SKILL.md contains Verification section."""
        content = (skill_path / "SKILL.md").read_text()
        assert "Verification" in content, "Missing Verification section"
