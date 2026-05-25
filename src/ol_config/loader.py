"""Config loader for Omni-Localizer."""
import os
from pathlib import Path
from typing import Any

import yaml

from ol_config.schema import ProjectConfig
from ol_logging.core import get_logger
from ol_terminology.glossary import load_glossary_from_path

_logger = get_logger("config")

def _load_env_file() -> None:
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

def load_config(path: str | Path) -> tuple[ProjectConfig, dict[str, Any]]:
    """Load and validate project configuration from YAML.

    Args:
        path: Path to YAML config file

    Returns:
        Tuple of (Validated ProjectConfig instance, glossary dict)
        Returns ({},) if glossary_path is None or loading fails.

    Raises:
        ValidationError: If config is invalid or missing required fields
        FileNotFoundError: If config file doesn't exist
        TypeError: If path is None

    """
    if path is None:
        raise TypeError("load_config() path must not be None")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    _logger.info(f"Loading config: {path}")
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)

        config = ProjectConfig(**data)
        _logger.info(f"Config loaded: {config.project_id}")

        glossary: dict[str, Any] = {}
        if config.glossary_path:
            try:
                glossary = load_glossary_from_path(
                    config.glossary_path, config_dir=Path(path).parent
                )
            except Exception as e:
                _logger.warning(f"Failed to load glossary, returning empty dict: {e}")
                glossary = {}

        return (config, glossary)
    except Exception as e:
        _logger.error(f"Failed to load config: {e}")
        raise

def validate_config(config: ProjectConfig) -> bool:
    """Validate config has required fields.

    Note: Pydantic validation already occurs during ProjectConfig construction
    in load_config(). This function exists for explicit validation calls if needed.
    """
    try:
        cfg_dict = config.model_dump()
        return cfg_dict is not None and cfg_dict.get("project_id") is not None
    except Exception:
        return False
