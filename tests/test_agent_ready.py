"""Tests for the OL agent-ready/v1 contract entry (OL#206).

The issue's acceptance: 5 pytest cases — all-green / ladder step 1 hit /
ladder step 2 hit / ladder step 3 blocked / exit code correct.  The
interpreter probe is stubbed so tests never depend on which venvs exist on
the running machine (machine facts are not repo facts).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent_ready.py"
_spec = importlib.util.spec_from_file_location("ol_agent_ready", _SCRIPT)
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)  # load by path: OL scripts/ is not a package,
                              # and `from scripts import ...` would shadow-hit
                              # the suite checkout's scripts/ package


def _venv_ok(_interpreter: str) -> tuple[int, str]:
    return 0, ""


def _venv_missing(_interpreter: str) -> tuple[int, str]:
    return 1, "ModuleNotFoundError"


class TestLadder:
    def test_all_green_when_keyed_and_venv_ok(self):
        env = {n: "x" for n in ar.HARNESS_LLM_ENV}
        report, code = ar.build_report(env=env, interpreter_probe=_venv_ok)
        assert code == 0
        assert report["ok"] is True and report["status"] == "ok"
        llm = report["checks"][0]
        assert llm["code"] == "ok"
        assert llm["ladder"][-1] == {"step": 3, "probe": "ask-human", "result": "not-needed"}

    def test_ladder_step1_harness_default_hits(self):
        env = {n: "x" for n in ar.HARNESS_LLM_ENV}
        llm = ar.llm_check(env)
        assert llm["code"] == "ok"
        assert llm["detail"].startswith("model access via ladder step 1")

    def test_ladder_step2_openai_compatible_hits(self):
        env = {n: "x" for n in ar.OPENAI_COMPAT_ENV}
        llm = ar.llm_check(env)
        assert llm["code"] == "ok"
        assert llm["detail"].startswith("model access via ladder step 2")

    def test_ladder_step3_blocked_without_any_key(self):
        llm = ar.llm_check({})
        assert llm["status"] == "blocked" and llm["code"] == "blocked:no-llm-key"
        assert llm["ladder"][-1] == {"step": 3, "probe": "ask-human", "result": "required"}
        assert llm["remedy"]  # the human at the screen needs a remedy line


class TestExitCodes:
    def test_no_llm_key_maps_to_exit_2(self):
        report, code = ar.build_report(env={}, interpreter_probe=_venv_ok)
        assert code == 2
        assert report["next_action"] == "provide base_url + key + model"

    def test_no_venv_maps_to_exit_4(self):
        report, code = ar.build_report(env={}, interpreter_probe=_venv_missing)
        assert code == 4
        codes = {c["code"] for c in report["checks"] if c["status"] == "blocked"}
        assert codes == {"blocked:no-llm-key", "blocked:no-venv"}

    @pytest.mark.parametrize("argv", [[], ["--compact"]])
    def test_main_json_contract_shape(self, argv, capsys, monkeypatch):
        # exit 2 deterministically: strip every key-shaped env var the ladder
        # could probe (machine facts must not decide a repo test) and stub
        # the interpreter probe so no real venv is consulted.
        import json

        for name in (*ar.HARNESS_LLM_ENV, *ar.OPENAI_COMPAT_ENV,
                     *ar._config_provider_env_names()):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(ar, "_run_module_probe", lambda _i: (0, ""))

        code = ar.main(argv)
        raw = capsys.readouterr().out
        payload = json.loads(raw)
        assert code == 2
        assert payload["schema"] == "agent-ready/v1"
        assert isinstance(payload["checks"], list)
        # --compact collapses the pretty-printer's inner newlines (the print()
        # trailing newline is always present)
        assert (raw.count("\n") <= 1) == (argv == ["--compact"])
