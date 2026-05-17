"""Pytest configuration for Omni-Localizer tests."""
import sys
from pathlib import Path

# Add src to Python path so ol_core, ol_md, etc. can be imported
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))