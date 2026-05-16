"""Format guard tests for Omni-Localizer."""
import pytest
from pathlib import Path
from ol_buses.format_guard import (
    validate_input_format,
    is_supported,
    get_supported_formats,
    FormatNotSupportedError,
    SUPPORTED_FORMATS,
)

class TestFormatGuard:
    """Test format guard functionality."""

    def test_md_format_accepted(self):
        """Test .md files are accepted."""
        assert validate_input_format('test.md') == 'md'
        assert is_supported('test.md') == True

    def test_xliff_format_accepted(self):
        """Test .xliff and .xlf files are accepted."""
        assert validate_input_format('test.xliff') == 'xliff'
        assert validate_input_format('test.xlf') == 'xliff'
        assert is_supported('test.xliff') == True
        assert is_supported('test.xlf') == True

    def test_unsupported_format_rejected(self):
        """Test unsupported formats raise FormatNotSupportedError."""
        for ext in ['.docx', '.json', '.txt', '.pdf', '.doc']:
            with pytest.raises(FormatNotSupportedError) as exc_info:
                validate_input_format(f'file{ext}')
            assert 'Supported formats' in str(exc_info.value)
            assert is_supported(f'file{ext}') == False

    def test_get_supported_formats(self):
        """Test get_supported_formats returns correct set."""
        formats = get_supported_formats()
        assert formats == SUPPORTED_FORMATS
        assert '.md' in formats
        assert '.xliff' in formats
        assert '.xlf' in formats
        assert '.json' not in formats

    def test_case_insensitive(self):
        """Test extensions are case insensitive."""
        assert validate_input_format('test.MD') == 'md'
        assert validate_input_format('test.XLIFF') == 'xliff'
        is_supported('test.Md') == True