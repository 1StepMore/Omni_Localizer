#!/usr/bin/env python3
"""coverage_matrix — OL 生产矩阵校验（issue OL#164）。

从源码派生「源格式 × 翻译模式 × 质量门 × MCP 工具」的真值，与
docs/dev/production-matrix.md 比对：行集合、工具集合、门数、头部计数
必须与派生值一致。

用法：
    python scripts/coverage_matrix.py --check     # 校验（exit 1 = 漂移）
    python scripts/coverage_matrix.py             # 打印派生真值

与 scripts/doc_inventory.py 同一哲学：矩阵必须能被源码证伪。
"""
from __future__ import annotations

import argparse
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MATRIX_PATH = ROOT / "docs" / "dev" / "production-matrix.md"


def _derive() -> dict:
    from ol_lqa.quality_gates import run_quality_gates
    from ol_mcp.tools import TOOL_REGISTRY

    gates = sorted(p.removesuffix("_enabled")
                   for p in inspect.signature(run_quality_gates).parameters
                   if p.endswith("_enabled"))
    return {
        "tools": sorted(TOOL_REGISTRY),
        "gates": gates,
        "channels": ["translate-md", "translate-xliff", "translate-batch"],
        "scenarios": _scenario_count(),
    }


def _scenario_count() -> int:
    scenarios = ROOT / "scenarios"
    if not scenarios.is_dir():
        return 0
    return len([
        p for p in scenarios.rglob("*.yaml")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    ])


_COVERAGE_MARKS = ("✅", "⚠️", "❌")
_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_-]+)`\s*\|(.+)\|\s*$")


def _parse_rows(section_header: str) -> list[tuple[str, str]]:
    if not MATRIX_PATH.is_file():
        raise SystemExit(f"missing {MATRIX_PATH} — write the matrix first")
    rows, in_section = [], False
    for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"## {section_header}"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            m = _ROW_RE.match(line)
            if m:
                rows.append((m.group(1), m.group(2)))
    return rows


def check() -> int:
    failures: list[str] = []
    truth = _derive()
    body = MATRIX_PATH.read_text(encoding="utf-8")

    # 1) 翻译通道行
    channel_rows = [f for f, _ in _parse_rows("Translation channels")]
    if set(channel_rows) != set(truth["channels"]):
        failures.append(
            f"channel rows out of sync: missing="
            f"{sorted(set(truth['channels']) - set(channel_rows))} "
            f"extra={sorted(set(channel_rows) - set(truth['channels']))}"
        )

    # 2) 质量门行：8 个门名必须逐个出现且带标注
    gate_rows = [f for f, _ in _parse_rows("Quality gates")]
    if set(gate_rows) != set(truth["gates"]):
        failures.append(
            f"gate rows out of sync: missing="
            f"{sorted(set(truth['gates']) - set(gate_rows))} "
            f"extra={sorted(set(gate_rows) - set(truth['gates']))}"
        )
    for _, rest in _parse_rows("Quality gates"):
        if not any(mark in rest for mark in _COVERAGE_MARKS):
            failures.append("a quality-gate row carries no ✅/⚠️/❌ mark")

    # 3) 工具名逐个出现
    for tool in truth["tools"]:
        if f"`{tool}`" not in body:
            failures.append(f"matrix does not mention tool `{tool}`")

    # 4) 头部计数行
    for pattern, expected in (
        (re.compile(r"MCP tools: \*\*(\d+)\*\*"), len(truth["tools"])),
        (re.compile(r"quality gates: \*\*(\d+)\*\*"), len(truth["gates"])),
        (re.compile(r"scenarios: \*\*(\d+)\*\*"), truth["scenarios"]),
    ):
        m = pattern.search(body)
        if not m:
            failures.append(f"matrix header missing count line: {pattern.pattern}")
        elif int(m.group(1)) != expected:
            failures.append(
                f"matrix header claims {m.group(0)!r} but source derives {expected}"
            )

    if failures:
        print("coverage matrix check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"coverage matrix check passed: {len(truth['channels'])} channels, "
        f"{len(truth['gates'])} gates, {len(truth['tools'])} tools, "
        f"{truth['scenarios']} scenarios in sync."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="coverage_matrix")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not args.check:
        truth = _derive()
        print(f"channels: {', '.join(truth['channels'])}")
        print(f"quality gates ({len(truth['gates'])}):", ", ".join(truth["gates"]))
        print(f"MCP tools ({len(truth['tools'])}):", ", ".join(truth["tools"]))
        print(f"scenarios: {truth['scenarios']}")
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
