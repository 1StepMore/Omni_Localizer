"""Regression test for C1: get_capabilities must report the live tool registry.

Before the fix, get_capabilities returned a hardcoded 17-name list while the
live server registered 21 tools, so an agent received a wrong contract. These
tests compare two independent sources: the JSON envelope and TOOL_REGISTRY.
"""
from __future__ import annotations

import json


def _capability_envelope() -> dict:
    from ol_mcp.get_capabilities import get_capabilities

    return json.loads(get_capabilities())


def test_get_capabilities_tools_set_equals_live_registry():
    """Given the live registry, the capabilities envelope must agree exactly.

    Given: the live server registry and the get_capabilities tool
    When: get_capabilities() is called
    Then: its tools list set-equals TOOL_REGISTRY.keys()
    """
    from ol_mcp.tools import TOOL_REGISTRY

    # When
    envelope = _capability_envelope()

    # Then
    reported = set(envelope["content"]["tools"])
    registry = set(TOOL_REGISTRY.keys())
    assert reported == registry, (
        "get_capabilities tools disagree with TOOL_REGISTRY: "
        f"only-in-envelope={sorted(reported - registry)}, "
        f"only-in-registry={sorted(registry - reported)}"
    )


def test_get_capabilities_reports_all_live_tools():
    """Given the live registry, capabilities must report the full count."""
    from ol_mcp.tools import TOOL_REGISTRY

    envelope = _capability_envelope()

    assert len(envelope["content"]["tools"]) == len(TOOL_REGISTRY)
    assert len(envelope["content"]["tools"]) == 21
