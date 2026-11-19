"""Translation-pool seam shared by the OL MCP translate tools.

``OMNI_TEST_FAKE_LLM=1`` must yield the SAME deterministic fake as the OL
CLI (cli/translate_xliff.py:352-358): ``ol_pool.fake._FakeModelPool``
echoes ``[{target_lang}] {source}``. The real ``ModelPool``'s own
test-mode short-circuit (router.py ``_test_mode``) returns the literal
string ``"placeholder"`` instead — which destroyed the ``" | "`` row
structure that ORF's xliff2xlsx fail-closes on (XLSX_MAP_MISMATCH), so
the MCP channel scored placeholder targets where the CLI scored proper
echoes. First exposed by the suite matrix's multi-cell xlsx fixture
(2026-11-20): the old single-cell fixture never exercised the row
structure, so both channels passed on different fake semantics.
"""
from __future__ import annotations

import os
from typing import Any


def translation_pool(config_path: str | None) -> Any:
    """Return the pool the translate tools should use (FAKE-aware)."""
    if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
        from ol_pool.fake import _FakeModelPool  # noqa: PLC0415
        return _FakeModelPool()
    from ol_pool.router import ModelPool  # noqa: PLC0415
    return ModelPool.get_instance(config_path)
