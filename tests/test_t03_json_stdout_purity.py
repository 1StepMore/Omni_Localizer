"""T-03 regression: ``--json`` stdout is exactly one parseable JSON object.

Plan gap T-03 (``.omo/plans/agent-oriented-gap-register.md`` §4.1,
"``--json`` stdout pollution"): under ``--json`` the OL CLI still wrote
human banners / progress / summaries to **stdout** in addition to the
machine-readable JSON:

* ``src/cli/translate_md.py`` — ``Using config: <project> (src -> tgt)``
* ``src/cli/batch.py`` — ``Using config:``, ``Found N files to process``
* ``src/ol_batch/summary.py`` — the rich "Batch Processing Summary" table
* ``src/ol_batch/progress.py`` — the rich progress bar

An agent that does ``json.loads(stdout)`` (the ``#json-parseable``
contract in ``scenarios/STANDARDS.md``) therefore failed even on a
successful run. The fix routes all human-facing output to **stderr**
when ``--json`` is set, leaving stdout as exactly one JSON object.

``test_*_stdout_single_object`` are the failing-first assertions: RED on
the unfixed code, GREEN once the banners move to stderr. The
``_characterization`` tests pin the existing JSON body shape so the fix
does not change schemas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ol_cli import app

runner = CliRunner()

# A minimal valid ProjectConfig: every role needs >= 2 models
# (primary + backup), enforced by the Pydantic schema.
_CONFIG_TEMPLATE = """\
project_id: t03-json-purity
source_lang: en
target_lang: zh
llm_pool:
  translation:
    - provider: openai
      model: fake-translation-1
      priority: 1
      role: translation
      api_key: fake-key
    - provider: openai
      model: fake-translation-2
      priority: 2
      role: translation
      api_key: fake-key
  judging:
    - provider: openai
      model: fake-judging-1
      priority: 1
      role: judging
      api_key: fake-key
    - provider: openai
      model: fake-judging-2
      priority: 2
      role: judging
      api_key: fake-key
  restoration:
    - provider: openai
      model: fake-restoration-1
      priority: 1
      role: restoration
      api_key: fake-key
    - provider: openai
      model: fake-restoration-2
      priority: 2
      role: restoration
      api_key: fake-key
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "ol-config.yaml"
    cfg.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    return cfg


def _parse_single_json(stdout: str) -> dict[str, Any]:
    """``json.loads`` the WHOLE stdout — rejects any banner/trailer."""
    parsed = json.loads(stdout)
    assert isinstance(parsed, dict), f"stdout JSON is not an object: {type(parsed)}"
    return parsed


def _translate_md_module():
    """Return the real ``cli.translate_md`` module (the name is shadowed
    in the ``cli`` package namespace by the command function)."""
    import cli.translate_md  # noqa: F401

    import sys

    return sys.modules["cli.translate_md"]


# ---------------------------------------------------------------------------
# translate-md --json
# ---------------------------------------------------------------------------


def test_translate_md_json_with_config_stdout_single_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ol translate-md -c cfg --json`` → stdout parses as one object.

    RED on the unfixed code: stdout was
    ``Using config: ...\\n{json}`` (``translate_md.py:1036``).
    """
    cfg = _write_config(tmp_path)
    md = tmp_path / "in.md"
    md.write_text("# Hello\n\nWorld\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    mod = _translate_md_module()

    async def _fake_translate(
        input_path: Path,
        output_path: Path,
        config_path: str | None,
        src: str,
        tgt: str,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        produced = Path(output_path) / Path(input_path).name
        produced.write_text("# Translated\n", encoding="utf-8")
        return str(produced)

    monkeypatch.setattr(mod, "_translate_md_async", _fake_translate)

    result = runner.invoke(
        app,
        [
            "translate-md",
            str(md),
            "-c",
            str(cfg),
            "-o",
            str(out),
            "--json",
            "--no-cache",
            "--no-restoration",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr[-800:]}"
    obj = _parse_single_json(result.stdout)
    assert obj["success"] is True
    assert obj["output_file"]


def test_translate_md_json_pipeline_failure_stdout_single_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pipeline failure + ``--json`` still emits ONE JSON object on stdout.

    The ``Using config:`` banner is printed *before* the failure, so on
    the unfixed code stdout was ``Using config: ...\\n{json error}``.
    """
    cfg = _write_config(tmp_path)
    md = tmp_path / "in.md"
    md.write_text("# Hello\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    mod = _translate_md_module()

    async def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("synthetic translation failure")

    monkeypatch.setattr(mod, "_translate_md_async", _boom)

    result = runner.invoke(
        app,
        [
            "translate-md",
            str(md),
            "-c",
            str(cfg),
            "-o",
            str(out),
            "--json",
            "--no-cache",
            "--no-restoration",
        ],
    )

    assert result.exit_code != 0, f"stdout: {result.stdout!r}"
    obj = _parse_single_json(result.stdout)
    assert obj["success"] is False
    assert obj["error"]


# ---------------------------------------------------------------------------
# translate-batch --json
# ---------------------------------------------------------------------------


def _patch_batch_deps(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    """Patch the batch internals so no LLM/network work happens.

    ``ModelPool.get_instance`` is replaced with a dummy (the config load
    still runs for real) and ``BatchProcessor.process_batch`` returns the
    supplied ``BatchResult``. This keeps ``_translate_batch_async``'s
    human output (``Found N files``, progress bar, summary) on the real
    code path.
    """
    import ol_batch.processor as processor_mod
    import ol_pool.router as router_mod

    monkeypatch.setattr(
        router_mod.ModelPool,
        "get_instance",
        staticmethod(lambda *a, **k: object()),
    )

    async def _fake_process_batch(self: Any, *args: Any, **kwargs: Any) -> Any:
        return result

    monkeypatch.setattr(processor_mod.BatchProcessor, "process_batch", _fake_process_batch)


def _make_batch_input(tmp_path: Path) -> Path:
    indir = tmp_path / "batch_in"
    indir.mkdir()
    (indir / "a.md").write_text("# A\n\ncontent\n", encoding="utf-8")
    return indir


def test_translate_batch_json_stdout_single_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ol translate-batch ... --json`` → stdout parses as one object.

    RED on the unfixed code: stdout carried ``Using config:``,
    ``Found 1 files to process``, the rich progress bar and the
    "Batch Processing Summary" table before the JSON
    (``batch.py:56,92`` + ``ol_batch/summary.py``).
    """
    from ol_batch.config import BatchResult

    cfg = _write_config(tmp_path)
    indir = _make_batch_input(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _patch_batch_deps(
        monkeypatch,
        BatchResult(succeeded=[Path("a.md")], failed=[], total=1),
    )

    result = runner.invoke(
        app,
        [
            "translate-batch",
            str(indir),
            "-c",
            str(cfg),
            "-o",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, f"stderr: {result.stderr[-800:]}"
    obj = _parse_single_json(result.stdout)
    assert obj["success"] is True


def test_translate_batch_json_failure_stdout_single_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch with failures + ``--json`` → stdout is ONE JSON object."""
    from ol_batch.config import BatchResult

    cfg = _write_config(tmp_path)
    indir = _make_batch_input(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _patch_batch_deps(
        monkeypatch,
        BatchResult(succeeded=[], failed=[(Path("a.md"), "boom")], total=1),
    )

    result = runner.invoke(
        app,
        [
            "translate-batch",
            str(indir),
            "-c",
            str(cfg),
            "-o",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code != 0, f"stdout: {result.stdout!r}"
    obj = _parse_single_json(result.stdout)
    assert obj["success"] is False
    assert obj["error"]
