"""Server configuration for OL MCP server."""
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for the OL MCP server."""

    config_path: str = "config/default.yaml"
    default_source_lang: str = "en"
    default_target_lang: str = "zh"
    concurrency_limit: int = 5
    timeout: float = 180.0