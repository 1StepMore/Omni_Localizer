"""Server configuration for OL MCP server."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    """Configuration for the OL MCP server.

    Timeout precedence:
    1. ``MCP_TOOL_TIMEOUT`` env var (unified cross-module name, Phase 2)
    2. Class default (120 seconds)
    """

    config_path: str = "config/default.yaml"
    default_source_lang: str = "en"
    default_target_lang: str = "zh"
    concurrency_limit: int = 5
    timeout: float = field(default_factory=lambda: float(os.environ.get("MCP_TOOL_TIMEOUT", "120")))
    metrics_dir: str = "/tmp/omni-metrics"


def get_metrics_dir() -> str:
    """Resolve the metrics output directory (env override)."""
    return os.environ.get("OMNI_METRICS_DIR", "/tmp/omni-metrics")