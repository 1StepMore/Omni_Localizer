"""Server configuration for OL MCP server."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for the OL MCP server."""

    config_path: str = "config/default.yaml"
    default_source_lang: str = "en"
    default_target_lang: str = "zh"
    concurrency_limit: int = 5
    timeout: float = 180.0
    metrics_dir: str = "/tmp/omni-metrics"


def get_metrics_dir() -> str:
    """Resolve the metrics output directory (env override)."""
    return os.environ.get("OMNI_METRICS_DIR", "/tmp/omni-metrics")