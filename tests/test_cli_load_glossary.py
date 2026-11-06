"""ADR 0007 Phase 2B-lite: the ``ol load-glossary`` CLI allowlist behavior.

The command used to hand-roll a comma-only env split with a silent
``[cwd, /tmp]`` fail-open fallback; it now reuses the MCP-side canonical
chain (``ol_mcp.security.get_default_validator`` —
``MCP_ALLOWED_DIRECTORIES`` > ``OL_MCP_ALLOWED_DIRS`` >
``OL_ALLOWED_DIRECTORIES``, os.pathsep + comma aware) and fails CLOSED
with remediation guidance when nothing is configured. An explicit
``--allow-dir`` still works on its own (the user's explicit choice is
never silent).
"""

from __future__ import annotations

import json

import pytest
from typer import Exit

from cli.load_glossary import load_glossary


@pytest.fixture(autouse=True)
def _clean_allowlist_env(monkeypatch):
    for var in (
        "MCP_ALLOWED_DIRECTORIES",
        "OL_MCP_ALLOWED_DIRS",
        "OL_ALLOWED_DIRECTORIES",
    ):
        monkeypatch.delenv(var, raising=False)


def _glossary_file(tmp_path):
    p = tmp_path / "glossary.json"
    p.write_text(
        json.dumps(
            {
                "API endpoint": {
                    "translation": "API 端点",
                    "confidence": 0.95,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return p


def test_fail_closed_without_any_allowlist(tmp_path):
    """No env var and no --allow-dir: fail CLOSED with CLI_USAGE_ERROR —
    the old behavior silently granted [cwd, /tmp]."""
    with pytest.raises(Exit) as excinfo:
        load_glossary(
            path=str(_glossary_file(tmp_path)), config_dir=None, allow_dir=None
        )
    assert excinfo.value.exit_code == 2


def test_unified_env_var_is_honored(tmp_path, monkeypatch, capsys):
    """MCP_ALLOWED_DIRECTORIES (the unified name) alone must allow the load."""
    f = _glossary_file(tmp_path)
    monkeypatch.setenv("MCP_ALLOWED_DIRECTORIES", str(tmp_path))
    with pytest.raises(Exit) as excinfo:
        load_glossary(path=str(f), config_dir=None, allow_dir=None)
    assert excinfo.value.exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["term_count"] == 1
    assert "API endpoint" in out["glossary"]


def test_legacy_env_var_is_honored(tmp_path, monkeypatch):
    """OL_MCP_ALLOWED_DIRS (the OL-specific name) alone must allow the load."""
    f = _glossary_file(tmp_path)
    monkeypatch.setenv("OL_MCP_ALLOWED_DIRS", str(tmp_path))
    with pytest.raises(Exit) as excinfo:
        load_glossary(path=str(f), config_dir=None, allow_dir=None)
    assert excinfo.value.exit_code == 0


def test_allow_dir_alone_suffices(tmp_path):
    """An explicit --allow-dir works even with no env configured — the
    user's explicit choice is not a silent fallback."""
    f = _glossary_file(tmp_path)
    with pytest.raises(Exit) as excinfo:
        load_glossary(path=str(f), config_dir=None, allow_dir=[str(tmp_path)])
    assert excinfo.value.exit_code == 0


def test_out_of_allowlist_path_is_denied(tmp_path, monkeypatch):
    """A path outside every configured dir is denied (OL_PATH_DENIED
    family), not loaded via the old [cwd, /tmp] umbrella."""
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    f = _glossary_file(outside)
    monkeypatch.setenv("OL_MCP_ALLOWED_DIRS", str(inside))
    with pytest.raises(Exit) as excinfo:
        load_glossary(path=str(f), config_dir=None, allow_dir=None)
    assert excinfo.value.exit_code == 2
