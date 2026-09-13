"""T-08 regression: verify_terms must validate ``glossary_path``.

The ``verify_terms`` MCP tool accepted a ``glossary_path`` and handed it
straight to ``ol_terminology.glossary.load_glossary_from_path`` with no
``PathValidator`` check — an agent could read any JSON file on the host
outside the MCP allowed-directories sandbox (issue: T-08 path-security
bypass). Every other path-taking OL tool (``load_glossary``, ``search_tm``,
``translate_xliff``) already routes through ``get_default_validator()`` and
returns the stable ``OL_PATH_DENIED`` code.

These tests are written red-first: before the fix, an out-of-allowlist
``glossary_path`` is loaded successfully (or fails with a generic load
error), never ``OL_PATH_DENIED``.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from ol_mcp._errors import OL_PATH_DENIED


@pytest.fixture
def allowed_dir(tmp_path):
    """An allowed directory containing one valid glossary JSON file."""
    d = tmp_path / "allowed"
    d.mkdir()
    (d / "glossary.json").write_text(
        json.dumps({"hello": {"translation": "你好", "confidence": 1.0}}),
        encoding="utf-8",
    )
    return d


@pytest.fixture
def outside_dir(tmp_path):
    """A directory that is NOT in the allowlist."""
    d = tmp_path / "outside"
    d.mkdir()
    (d / "secret.json").write_text(
        json.dumps({"secret": {"translation": "机密", "confidence": 1.0}}),
        encoding="utf-8",
    )
    return d


@pytest.fixture
def allowlist_env(allowed_dir, monkeypatch):
    """Point the OL validator at ``allowed_dir`` only."""
    monkeypatch.setenv("MCP_ALLOWED_DIRECTORIES", str(allowed_dir))
    monkeypatch.delenv("OL_MCP_ALLOWED_DIRS", raising=False)
    monkeypatch.delenv("OL_ALLOWED_DIRECTORIES", raising=False)
    return allowed_dir


def _invoke(glossary_path: str) -> dict:
    from ol_mcp.tools import VerifyTermsInput
    from ol_mcp.verify_terms import verify_terms

    params = VerifyTermsInput(
        source="hello world",
        target="你好 世界",
        glossary_path=glossary_path,
    )
    return json.loads(asyncio.run(verify_terms(params)))


def test_traversal_glossary_path_denied(allowlist_env):
    """A ``..`` traversal glossary_path must yield OL_PATH_DENIED."""
    evil = str(allowlist_env / ".." / ".." / "etc" / "passwd.json")
    result = _invoke(evil)
    assert result["success"] is False
    assert result["error"]["code"] == OL_PATH_DENIED


def test_out_of_allowlist_glossary_path_denied(allowlist_env, outside_dir):
    """A readable JSON glossary outside the allowlist must yield OL_PATH_DENIED."""
    result = _invoke(str(outside_dir / "secret.json"))
    assert result["success"] is False
    assert result["error"]["code"] == OL_PATH_DENIED


def test_allowed_glossary_path_still_works(allowlist_env):
    """A glossary inside the allowlist must still load (no over-blocking)."""
    result = _invoke(str(allowlist_env / "glossary.json"))
    assert result["success"] is True
    assert result["content"]["total_terms_checked"] == 1


def test_inline_glossary_bypasses_path_validation(allowlist_env):
    """Inline glossary (no path) must not require any validator access."""
    from ol_mcp.tools import VerifyTermsInput
    from ol_mcp.verify_terms import verify_terms

    params = VerifyTermsInput(
        source="hello world",
        target="你好 世界",
        glossary={"hello": {"translation": "你好", "confidence": 1.0}},
    )
    result = json.loads(asyncio.run(verify_terms(params)))
    assert result["success"] is True
