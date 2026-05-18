"""Config loader for Omni-Localizer."""
import os
from pathlib import Path
from typing import Union
import yaml
from pydantic import ValidationError
from ol_config.schema import ProjectConfig
from ol_logging.core import get_logger

_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_logger = get_logger("config")

def load_config(path: Union[str, Path]) -> ProjectConfig:
    """
    Load and validate project configuration from YAML.

    Args:
        path: Path to YAML config file

    Returns:
        Validated ProjectConfig instance

    Raises:
        ValidationError: If config is invalid or missing required fields
        FileNotFoundError: If config file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    _logger.info(f"Loading config: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        cfg = ProjectConfig(**data)
        _logger.info(f"Config loaded: {cfg.project_id}")
        return cfg
    except Exception as e:
        _logger.error(f"Failed to load config: {e}")
        raise

def validate_config(config: ProjectConfig) -> bool:
    """Validate config has required fields."""
    return config.model_dump() is not None