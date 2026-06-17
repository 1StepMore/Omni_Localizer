"""Config loader for Omni-Localizer."""
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ol_config.schema import ProjectConfig
from ol_logging.core import get_logger
from ol_terminology.glossary import load_glossary_from_path

_logger = get_logger("config")


# 2026-06-17 round 8 (FIX-#24): hardcoded API key detector for YAML configs.
# Tracked files (default.yaml) must use ${ENV_VAR}; literals are rejected.
_HARDCODED_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                # OpenAI / Anthropic
    re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}"),             # NVIDIA NIM
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),                  # Groq
    re.compile(r"^[a-f0-9]{16,}\.[A-Za-z0-9_\-]{12,}"),   # Zhipu MiniMax
)


def _is_env_ref(value: str) -> bool:
    """Return True if value is a ${VAR} interpolation (not a literal)."""
    return value.startswith("${") and value.endswith("}")


def _check_for_hardcoded_secrets(data: dict[str, Any]) -> list[str]:
    """Scan parsed YAML for hardcoded api_key literals.

    Returns a list of "<role>/<model>: <key-prefix>..." messages for
    any api_key that matches a known key pattern AND is not an env
    var interpolation. Empty list = clean.
    """
    findings: list[str] = []
    pool = data.get("llm_pool", {}) or {}
    for role in ("translation", "judging", "restoration"):
        for entry in pool.get(role, []) or []:
            api_key = entry.get("api_key")
            if not isinstance(api_key, str):
                continue
            if _is_env_ref(api_key):
                continue
            for pattern in _HARDCODED_KEY_PATTERNS:
                if pattern.search(api_key):
                    preview = api_key[:12] + "..." if len(api_key) > 12 else api_key
                    findings.append(
                        f"{role}/{entry.get('model', '?')}: "
                        f"hardcoded key matches {pattern.pattern!r} "
                        f"(preview: {preview})"
                    )
                    break
    return findings


class SecurityError(Exception):
    """Raised when config contains hardcoded secrets."""

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
    _load_env_file()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    _logger.info(f"Loading config: {path}")
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # 2026-06-17 round 8 (FIX-#24): reject hardcoded API keys before
        # Pydantic validates the config. Catches re-introduction of literals
        # into tracked config files. Opt-out: OL_ALLOW_HARDCODED_KEYS=1 for
        # gitignored local.yaml during real-LLM local development.
        if os.environ.get("OL_ALLOW_HARDCODED_KEYS") != "1":
            findings = _check_for_hardcoded_secrets(data or {})
            if findings:
                for f in findings:
                    _logger.error(f"Security: {f}")
                raise SecurityError(
                    f"Hardcoded API key(s) detected in {path}. "
                    f"Use ${{ENV_VAR}} interpolation in tracked config files. "
                    f"Per Omni_Localizer/.gitignore: 'default.yaml is tracked as "
                    f"a TEMPLATE — never put real keys/endpoints in it. Use "
                    f"local.yaml.' Findings: {findings}"
                )

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
