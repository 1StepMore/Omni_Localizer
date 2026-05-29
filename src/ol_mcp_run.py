#!/usr/bin/env python3
"""OL MCP server entry point — runs directly in FastMCP's own event loop."""
import sys
import os

sys.path.insert(0, "/mnt/d/Hermes-Workspace/01-Projects/Omni_Localizer/src")
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# E2E-05 fix: prevent liteLLM from auto-adding unconfigured embedding models
os.environ.setdefault("LITELLM_OFFLINE", "true")
os.environ.setdefault("LITELLM_DISABLE_MODEL_LIST_AUTO_UPDATE", "true")

from ol_mcp.tools import mcp

# FastMCP.run() is sync — it creates its own anyio event loop internally
mcp.run(transport="stdio")