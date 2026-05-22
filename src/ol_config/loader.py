"""Config loader for Omni-Localizer."""
import os
from pathlib import Path
from typing import Union
import yaml
from pydantic import ValidationError
from ol_config.schema import ProjectConfig, _check_env_vars
from ol_logging.core import get_logger

_logger = get_logger("config")

def _load_env_file() -> None:
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

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
        TypeError: If path is None
    """
    if path is None:
        raise TypeError("load_config() path must not be None")
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