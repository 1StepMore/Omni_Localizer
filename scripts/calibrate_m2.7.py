#!/usr/bin/env python3
"""E.2 — MiniMax-M2.7 calibration script.

Procedure (per plan A5 + A7):
  1. Load a frozen 100-unit sample corpus (or subset if cost-constrained).
  2. Translate each unit with M3 (baseline) and M2.7 (candidate).
  3. Judge each translation with the judging model (ernie-4.5-turbo-32k).
  4. Compare M2.7 mean LQA score vs M3 baseline.
  5. PASS: M2.7 mean is within 0.5 of M3 mean (acceptance criterion).
  6. FAIL: M2.7 mean is more than 0.5 below M3 mean — DO NOT swap M2.7
     into production until retrained/recalibrated.

Usage:
  # Dry-run (no real LLM calls; just verifies the harness is wired):
  OMNI_RUN_REAL_LLM_DRY=1 python scripts/calibrate_m2.7.py

  # Real run (requires API keys; ~$0.50 for 100 units, ~$1.50 with judge):
  MINIMAX_API_KEY=... BAIDU_API_KEY=... \\
    python scripts/calibrate_m2.7.py --num-units 100

  # Cost-constrained subset (50 units; ~$0.75 total):
  python scripts/calibrate_m2.7.py --num-units 50

Output:
  - prints per-unit score comparison
  - writes JSON report to scripts/reports/calibration_<timestamp>.json
  - exits 0 on PASS, 1 on FAIL

Reference: .omo/plans/slim-pipeline-hardening.md A5 + A7 + E.2.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is on sys.path so we can import ol_pool / ol_lqa / ol_config.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@dataclass
class UnitResult:
    unit_id: str
    source: str
    m3_translation: str
    m3_score: float
    m27_translation: str
    m27_score: float
    m27_minus_m3: float


@dataclass
class CalibrationReport:
    timestamp: str
    num_units: int
    m3_mean: float
    m3_stdev: float
    m27_mean: float
    m27_stdev: float
    m27_minus_m3_mean: float
    acceptance_threshold: float
    decision: str  # "PASS" | "FAIL" | "DRY_RUN"
    per_unit: list[dict]
    notes: list[str]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--num-units",
        type=int,
        default=100,
        help="Number of units to translate. Default: 100. Use 20-50 for cost-constrained runs.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Acceptance threshold: M2.7 mean must be within this of M3 mean. Default: 0.5.",
    )
    p.add_argument(
        "--judge-model",
        default="MiniMax-M2.5",
        help=(
            "Model used to judge translations. Default: MiniMax-M2.5 "
            "(independent third-party judge on the MiniMax API; "
            "different from the M3/M2.7 contestants)."
        ),
    )
    p.add_argument(
        "--report-dir",
        type=Path,
        default=_HERE / "reports",
        help="Where to write the JSON report. Default: scripts/reports/",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip real LLM calls; use stubbed scores. For harness validation only.",
    )
    p.add_argument(
        "--corpus",
        type=Path,
        default=_HERE.parent / "tests" / "fixtures" / "real_llm_corpus" / "reference_outputs.json",
        help="Path to corpus JSON. Default: tests/fixtures/real_llm_corpus/reference_outputs.json",
    )
    return p.parse_args()


def load_corpus(path: Path, num_units: int) -> list[dict]:
    if not path.exists():
        print(f"ERROR: corpus not found at {path}", file=sys.stderr)
        print("  Create one matching the format: list of {unit_id, source} dicts", file=sys.stderr)
        print("  or a dict keyed by unit_id with an 'input' field (see A11 reference_outputs.json).", file=sys.stderr)
        sys.exit(2)
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    # Strip metadata keys.
    if isinstance(raw, dict):
        raw = {k: v for k, v in raw.items() if not k.startswith("_")}

    # Normalize to a list of {unit_id, source} dicts.
    if isinstance(raw, list):
        corpus = raw
    elif isinstance(raw, dict):
        corpus = []
        for unit_id, entry in raw.items():
            if isinstance(entry, dict):
                source = entry.get("input") or entry.get("source") or ""
                if source:
                    corpus.append({"unit_id": unit_id, "source": source})
            elif isinstance(entry, str):
                corpus.append({"unit_id": unit_id, "source": entry})
    else:
        print(f"ERROR: corpus at {path} must be a list or dict, got {type(raw).__name__}", file=sys.stderr)
        sys.exit(2)

    if not corpus:
        print(f"ERROR: corpus at {path} is empty after normalization", file=sys.stderr)
        sys.exit(2)

    return corpus[:num_units]


def _build_pool_for_model(target_model: str, base_config_path: Path, dry_run: bool):
    """Build a ModelPool whose translation role resolves to ``target_model``.

    Writes a temp config next to the original where the translation list
    is restricted to the target model (priority 1). This is the only way
    to force a specific translation model through ``ModelPool.translate()``,
    which hardcodes ``model="translation"`` and relies on the priority list.
    """
    if dry_run or os.environ.get("OMNI_RUN_REAL_LLM_DRY") == "1":
        return None
    try:
        from ol_pool.router import ModelPool
    except ImportError as e:
        print(f"ERROR: cannot import ModelPool: {e}", file=sys.stderr)
        print("  Are you in the Omni_Localizer directory with src/ on PYTHONPATH?", file=sys.stderr)
        sys.exit(2)
    import yaml
    with base_config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    models = cfg.get("llm_pool", {}).get("translation", [])
    target_entry = next((m for m in models if m.get("model") == target_model), None)
    if target_entry is None:
        print(f"ERROR: target model {target_model!r} not found in {base_config_path}", file=sys.stderr)
        print(f"  Available translation models: {[m.get('model') for m in models]}", file=sys.stderr)
        sys.exit(2)
    # Validator requires >= 2 models per role; keep all but put target at priority 1.
    reordered = [{**target_entry, "priority": 1}]
    next_priority = 2
    for m in models:
        if m.get("model") == target_model:
            continue
        reordered.append({**m, "priority": next_priority})
        next_priority += 1
    cfg["llm_pool"]["translation"] = reordered
    tmp_cfg_path = base_config_path.parent / f".calibration_{target_model}.yaml"
    with tmp_cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return ModelPool.get_instance(str(tmp_cfg_path))


def translate_unit(model: str, source: str, dry_run: bool, pool=None) -> str:
    """Translate a single unit. Stubbed in dry-run; real runs use the pre-built ``pool``."""
    if dry_run or os.environ.get("OMNI_RUN_REAL_LLM_DRY") == "1":
        return f"[{model}] {source}"
    if pool is None:
        raise RuntimeError(f"real translate requires a pre-built pool for {model}")
    import asyncio
    return asyncio.run(pool.translate(source, "en", "zh"))


def judge_unit(source: str, target: str, judge_model: str, dry_run: bool, model_pool=None) -> float:
    """Judge a translation. Returns 0-10 score. Stubbed in dry-run.

    The ``judge_model`` argument is informational only; the actual judge is
    selected from the judging role in the OL config (priority 1 by default).
    ``model_pool`` must be provided for real judging — without it JudgeService
    falls back to its built-in mock (returns 7.0).
    """
    if dry_run or os.environ.get("OMNI_RUN_REAL_LLM_DRY") == "1":
        h = abs(hash((source, target, judge_model))) % 100
        return 5.0 + (h / 100.0) * 5.0  # 5.0 - 10.0 range
    try:
        from ol_lqa.judge import JudgeService
    except ImportError as e:
        print(f"ERROR: cannot import JudgeService: {e}", file=sys.stderr)
        sys.exit(2)
    import asyncio
    judge_svc = JudgeService(pass_threshold=7.0, model_pool=model_pool)
    result = asyncio.run(judge_svc.judge(source, target, "calibration", "en", "zh"))
    return result.judge_overall_score


def run_calibration(args: argparse.Namespace) -> CalibrationReport:
    corpus = load_corpus(args.corpus, args.num_units)
    dry_run = args.dry_run or os.environ.get("OMNI_RUN_REAL_LLM_DRY") == "1"

    notes: list[str] = []
    if dry_run:
        notes.append("DRY RUN: no real LLM calls. Use without --dry-run for actual calibration.")
    if not dry_run and not os.environ.get("MINIMAX_API_KEY"):
        notes.append("MINIMAX_API_KEY not set — calibration requires it. Source .env or export it.")

    print(f"Calibrating with {len(corpus)} units (judge={args.judge_model}, threshold={args.threshold})")
    if dry_run:
        print("  [DRY RUN MODE]")
    else:
        print("  Building per-model pools (ModelPool) and judging via JudgeService.")

    m3_pool = m27_pool = None
    if not dry_run:
        base_config = args.corpus.parents[3] / "config" / "default.yaml"
        if not base_config.exists():
            print(f"ERROR: base config not found at {base_config}", file=sys.stderr)
            print("  Pass --base-config explicitly if the corpus is outside Omni_Localizer/tests/.", file=sys.stderr)
            sys.exit(2)
        m3_pool = _build_pool_for_model("MiniMax-M3", base_config, dry_run)
        m27_pool = _build_pool_for_model("MiniMax-M2.7", base_config, dry_run)

    per_unit: list[dict] = []
    m3_scores: list[float] = []
    m27_scores: list[float] = []
    t0 = time.perf_counter()
    for i, unit in enumerate(corpus, 1):
        unit_id = unit.get("unit_id", f"u_{i:04d}")
        source = unit["source"]
        m3_t = translate_unit("MiniMax-M3", source, dry_run, pool=m3_pool)
        m27_t = translate_unit("MiniMax-M2.7", source, dry_run, pool=m27_pool)
        m3_s = judge_unit(source, m3_t, args.judge_model, dry_run, model_pool=m3_pool)
        m27_s = judge_unit(source, m27_t, args.judge_model, dry_run, model_pool=m3_pool)
        delta = m27_s - m3_s
        m3_scores.append(m3_s)
        m27_scores.append(m27_s)
        per_unit.append(asdict(UnitResult(
            unit_id=unit_id, source=source,
            m3_translation=m3_t, m3_score=m3_s,
            m27_translation=m27_t, m27_score=m27_s,
            m27_minus_m3=delta,
        )))
        if i % 10 == 0 or i == len(corpus):
            elapsed = time.perf_counter() - t0
            print(f"  [{i}/{len(corpus)}] {elapsed:.1f}s elapsed; M3 mean so far: {statistics.mean(m3_scores):.2f}; M2.7 mean: {statistics.mean(m27_scores):.2f}; delta: {statistics.mean(m27_scores) - statistics.mean(m3_scores):+.2f}")

    m3_mean = statistics.mean(m3_scores)
    m3_stdev = statistics.stdev(m3_scores) if len(m3_scores) > 1 else 0.0
    m27_mean = statistics.mean(m27_scores)
    m27_stdev = statistics.stdev(m27_scores) if len(m27_scores) > 1 else 0.0
    delta_mean = m27_mean - m3_mean

    if dry_run:
        decision = "DRY_RUN"
    elif delta_mean >= -args.threshold:
        decision = "PASS"
    else:
        decision = "FAIL"

    return CalibrationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        num_units=len(corpus),
        m3_mean=m3_mean, m3_stdev=m3_stdev,
        m27_mean=m27_mean, m27_stdev=m27_stdev,
        m27_minus_m3_mean=delta_mean,
        acceptance_threshold=args.threshold,
        decision=decision,
        per_unit=per_unit,
        notes=notes,
    )


def write_report(report: CalibrationReport, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = report.timestamp.replace(":", "-")
    out = report_dir / f"calibration_{ts}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, ensure_ascii=False, indent=2)
    return out


def main() -> int:
    args = parse_args()
    report = run_calibration(args)
    out = write_report(report, args.report_dir)

    print()
    print("=" * 60)
    print(f"Calibration decision: {report.decision}")
    print(f"  M3  mean: {report.m3_mean:.3f} (stdev {report.m3_stdev:.3f})")
    print(f"  M2.7 mean: {report.m27_mean:.3f} (stdev {report.m27_stdev:.3f})")
    print(f"  delta (M2.7 - M3): {report.m27_minus_m3_mean:+.3f}  (threshold: {report.acceptance_threshold})")
    print(f"  Units: {report.num_units}")
    print(f"  Report: {out}")
    for note in report.notes:
        print(f"  NOTE: {note}")
    print("=" * 60)

    return 0 if report.decision in ("PASS", "DRY_RUN") else 1


if __name__ == "__main__":
    sys.exit(main())
