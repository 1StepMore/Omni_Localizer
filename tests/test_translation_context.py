"""TranslationContext tests for Omni-Localizer."""
from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit


class TestTranslationContext:
    """Test TranslationContext dataclass."""

    def test_creation(self):
        """Test TranslationContext can be created."""
        ctx = TranslationContext(
            file_path="test.md",
            channel_type=ChannelType.MD,
            original_full_text="Hello {{_OL_TAG_1_}}",
            units=[],
            glossary={},
            config={},
        )
        assert ctx.file_path == "test.md"
        assert ctx.channel_type == ChannelType.MD
        assert ctx.original_full_text == "Hello {{_OL_TAG_1_}}"

    def test_to_json(self):
        """Test JSON serialization."""
        ctx = TranslationContext(
            file_path="test.md",
            channel_type=ChannelType.MD,
            original_full_text="Hello",
            units=[],
            glossary={},
            config={},
        )
        json_data = ctx.to_json()
        assert json_data["file_path"] == "test.md"
        assert json_data["channel_type"] == "md"

    def test_from_json(self):
        """Test JSON deserialization."""
        data = {
            "file_path": "test.xliff",
            "channel_type": "xliff",
            "original_full_text": "Hello",
            "units": [],
            "glossary": {},
            "config": {},
        }
        ctx = TranslationContext.from_json(data)
        assert ctx.file_path == "test.xliff"
        assert ctx.channel_type == ChannelType.XLIFF

    def test_get_unit_by_id(self):
        """Test getting unit by ID."""
        units = [
            TranslationUnit(unit_id="u1", source_text="Hello"),
            TranslationUnit(unit_id="u2", source_text="World"),
        ]
        ctx = TranslationContext(
            file_path="test.md",
            channel_type=ChannelType.MD,
            original_full_text="Hello World",
            units=units,
            glossary={},
            config={},
        )
        found = ctx.get_unit_by_id("u2")
        assert found is not None
        assert found.source_text == "World"

        not_found = ctx.get_unit_by_id("u999")
        assert not_found is None
