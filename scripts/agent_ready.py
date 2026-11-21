#!/usr/bin/env python3
"""agent_ready.py — Omni_Localizer 的唯一 agent 接手入口（OL#206）。

输出 ``agent-ready/v1`` JSON 契约 + 契约退出码，与套件仓
``scripts/agent/agent_ready.py``（suite#379/#389）是**同一套契约**：
schema、probe 形状、退出码语义逐字段一致，只是探测对象换成 OL 本仓
（模块集、config 声明）。不做第二套口径。

退出码（机器判据，不靠日志）：
    0 = 全绿
    2 = blocked:no-llm-key
    3 = blocked:missing-dep（OL 当前无外部二进制依赖，此码保留为契约位，
        现有检查集不会产出）
    4 = 其它 blocked（no-venv 或混合）

模型阶梯（代码实现，不是文档话术；禁硬编码厂商）：
    1. harness 默认模型 seam（OMNI_AGENT_LLM_BASE_URL/API_KEY/MODEL）
    2. 本机 OpenAI 兼容端点/凭据（OPENAI_BASE_URL/API_KEY/MODEL）
       + OL config 里 ``api_key: ${VAR}`` 声明的环境变量（presence-only）
    3. 都不行 ⇒ blocked:no-llm-key + remedy，由屏幕前的人决定给什么。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

OL_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "agent-ready/v1"

HARNESS_LLM_ENV = ("OMNI_AGENT_LLM_BASE_URL", "OMNI_AGENT_LLM_API_KEY", "OMNI_AGENT_LLM_MODEL")
OPENAI_COMPAT_ENV = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")

# OL 的 agent 面两半：CLI（ol_cli/ol_config/ol_pool）+ MCP（ol_mcp）。
# 解释器探活 = 能全部 import（fail-closed：缺一件 ⇒ 后面全是假红/假绿）。
OL_MODULES = ("ol_cli", "ol_config", "ol_pool", "ol_mcp")

_PROVIDER_ENV_RE = re.compile(r"api_key:\s*\$\{([A-Z][A-Z0-9_]*)\}")


# ---------------------------------------------------------------------------
# Ladder probes (step 1 / step 2). Presence-only: never read or echo values.
# ---------------------------------------------------------------------------
def probe_harness_llm(env: dict) -> dict:
    """Step 1 — harness-injected default model seam."""
    hit = all(env.get(n) for n in HARNESS_LLM_ENV)
    return {"step": 1, "probe": "harness-default", "result": "ok" if hit else "absent"}


def _config_provider_env_names() -> list[str]:
    """Env var names declared by OL configs' ``api_key: ${VAR}`` entries.

    Config-driven: vendor names live in OL's own configs (which this repo
    ships); this code learns only the *names*, so no vendor is hardcoded and
    a config change flows through automatically (OL#205 的阶梯原则).
    """
    names: list[str] = []
    for cfg in sorted(OL_ROOT.glob("config/*.yaml")):
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _PROVIDER_ENV_RE.finditer(text):
            name = m.group(1)
            if name not in names:
                names.append(name)
    return names


def probe_openai_compatible(env: dict) -> dict:
    """Step 2a — machine-local OpenAI-compatible endpoint/credentials."""
    hit = all(env.get(n) for n in OPENAI_COMPAT_ENV)
    return {"step": 2, "probe": "env:OPENAI_COMPATIBLE", "result": "ok" if hit else "absent"}


def probe_suite_config(env: dict) -> dict:
    """Step 2b — credentials declared by OL's configs (presence-only)."""
    names = _config_provider_env_names()
    if not names:
        return {"step": 2, "probe": "ol-config", "result": "unknown"}
    hit = [n for n in names if env.get(n)]
    result = "ok" if hit else "absent"
    return {"step": 2, "probe": "ol-config", "result": result,
            "detail": f"present: {sorted(hit)}" if hit else f"declared: {names}"}


def llm_check(env: dict) -> dict:
    """Run the ladder in order; first hit wins, ask-human is the last resort."""
    ladder = [probe_harness_llm(env), probe_openai_compatible(env), probe_suite_config(env)]
    hit = next((e for e in ladder if e["result"] == "ok"), None)
    if hit is not None:
        ladder.append({"step": 3, "probe": "ask-human", "result": "not-needed"})
        return {"id": "llm", "status": "ok", "code": "ok",
                "detail": f"model access via ladder step {hit['step']} ({hit['probe']})",
                "ladder": ladder, "remedy": ""}
    ladder.append({"step": 3, "probe": "ask-human", "result": "required"})
    return {"id": "llm", "status": "blocked", "code": "blocked:no-llm-key",
            "detail": "no usable model on any ladder step",
            "ladder": ladder,
            "remedy": "provide base_url + key + model via the harness seam "
                      f"({HARNESS_LLM_ENV[0]}/{HARNESS_LLM_ENV[1]}/{HARNESS_LLM_ENV[2]}) "
                      "or OpenAI-compatible env, or ask the human at the screen"}


# ---------------------------------------------------------------------------
# Interpreter (venv) check — platform-aware candidates (suite#394 同款).
# ---------------------------------------------------------------------------
def _safe_exists(path: Path) -> bool:
    """``exists()`` that survives unstat-able paths (WinError 1920 on WSL dirs)."""
    try:
        return path.exists()
    except OSError:
        return False


def _default_interpreter_candidates() -> list[str]:
    cands: list[str] = []
    venv_posix = OL_ROOT / ".venv" / "bin" / "python"
    venv_win = OL_ROOT / ".venv_win" / "Scripts" / "python.exe"
    if os.name == "nt":
        cands += [str(venv_win), str(venv_posix)]
    else:
        cands += [str(venv_posix), str(venv_win)]
    cands.append(sys.executable)
    return cands


def interpreter_check(run_probe: Callable[[str], tuple[int, str]] | None = None) -> dict:
    """A usable interpreter = imports the four OL modules (fail-closed)."""
    if run_probe is None:
        run_probe = _run_module_probe

    tried: list[dict] = []
    for cand in _default_interpreter_candidates():
        rc, _out = run_probe(cand)
        tried.append({"interpreter": cand, "result": "ok" if rc == 0 else "absent"})
        if rc == 0:
            return {"id": "venv", "status": "ok", "code": "ok",
                    "detail": f"usable interpreter: {cand}",
                    "tried": tried, "remedy": ""}
    return {"id": "venv", "status": "blocked", "code": "blocked:no-venv",
            "detail": "no interpreter imports " + ", ".join(OL_MODULES),
            "tried": tried,
            "remedy": "create the OL venv: uv sync (OL repo root) or "
                      "pip install -e . into an interpreter on PATH"}


def _run_module_probe(interpreter: str) -> tuple[int, str]:
    """Run ``import`` probe for the OL modules under ``interpreter``."""
    code = "import importlib; import sys; " + "; ".join(
        f"importlib.import_module({m!r})" for m in OL_MODULES)
    try:
        r = subprocess.run(  # noqa: S603
            [interpreter, "-c", code], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, repr(exc)
    return r.returncode, (r.stderr or "")[-200:]


# ---------------------------------------------------------------------------
# Report assembly + exit codes.
# ---------------------------------------------------------------------------
def build_report(env: dict | None = None,
                 interpreter_probe: Callable[[str], tuple[int, str]] | None = None,
                 ) -> tuple[dict, int]:
    """Build the agent-ready/v1 payload and its contract exit code.

    ``interpreter_probe`` is injectable so tests can stub the environment
    without faking files on disk.  OL declares no external-binary deps, so
    there is no deps check; the exit-3 contract slot stays reserved.
    """
    env = os.environ if env is None else env

    checks: list[dict] = [llm_check(env), interpreter_check(run_probe=interpreter_probe)]

    blocked = {c["id"]: c["code"] for c in checks if c["status"] == "blocked"}
    codes = set(blocked.values())

    if not blocked:
        exit_code = 0
        status = "ok"
        next_action = "none"
    elif codes == {"blocked:no-llm-key"}:
        exit_code = 2
        status = "blocked"
        next_action = "provide base_url + key + model"
    elif codes == {"blocked:missing-dep"}:  # pragma: no cover — reserved slot
        exit_code = 3
        status = "blocked"
        next_action = "install missing deps"
    else:  # no-venv or any mixed combination
        exit_code = 4
        status = "blocked"
        next_action = "fix environment first (see blocked checks' remedy)"

    report = {
        "schema": SCHEMA,
        "ok": not blocked,
        "status": status,
        "checks": checks,
        "next_action": next_action,
    }
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent_ready.py")
    ap.add_argument("--compact", action="store_true", help="one-line JSON")
    args = ap.parse_args(argv)

    report, code = build_report()
    print(json.dumps(report, indent=None if args.compact else 2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
