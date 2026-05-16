"""RepairContext tests for Omni-Localizer."""
import pytest
from ol_core.dataclass import RepairContext

class TestRepairContext:
    """Test RepairContext dataclass."""

    def test_creation(self):
        """Test RepairContext can be created."""
        rc = RepairContext(
            unit_id="u1",
            shield_map={"tag1": "{{_OL_CODE_abc_}}"},
            original_text="Code block here",
            anchor_words=["Code"],
            max_retries=3
        )
        assert rc.unit_id == "u1"
        assert rc.shield_map == {"tag1": "{{_OL_CODE_abc_}}"}
        assert rc.original_text == "Code block here"
        assert rc.anchor_words == ["Code"]
        assert rc.max_retries == 3

    def test_defaults(self):
        """Test default values."""
        rc = RepairContext(
            unit_id="u1",
            shield_map={},
            original_text="text"
        )
        assert rc.anchor_words == []
        assert rc.max_retries == 3

    def test_all_fields(self):
        """Test all fields present."""
        rc = RepairContext(
            unit_id="test_unit",
            shield_map={"code1": "```python```", "math1": "$x^2$"},
            original_text="Code and math",
            anchor_words=["Code", "math"],
            max_retries=5
        )
        assert rc.unit_id == "test_unit"
        assert len(rc.shield_map) == 2
        assert len(rc.anchor_words) == 2