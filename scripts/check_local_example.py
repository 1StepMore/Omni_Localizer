#!/usr/bin/env python
"""CI gate (OL#195): `config/local.example.yaml` must track LLMPoolConfig.

`config/local.yaml` — the model pool's single source of truth — is
gitignored, so the example file is the only on-repo template. Without a
gate it drifts silently from the pydantic schema (a renamed field, a new
hard constraint) and every new machine copies a broken template.

What is asserted:
  1. The file parses through the REAL loader (`ol_config.loader.load_config`),
     so schema validation and the hardcoded-key SecurityError scan both run,
     exactly as a user's config/local.yaml would be loaded.
  2. Every role (translation/judging/restoration/profiling) has >= 2 tiers.
     The schema hard-enforces 3 of the 4; this gate also pins profiling so
     the template stays four-role homogeneous.
  3. Every `api_key` is a `${ENV_VAR}` reference — no literal keys, ever.

Wired as a named step in the `test-full` job of .github/workflows/test.yml
(the job that already carries the doc-inventory / coverage-matrix --check
gates; no new job was added). Break evidence (OL#195): delete one role's
P2 tier -> this script exits 1 -> the step goes red.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE_PATH = _REPO_ROOT / "config" / "local.example.yaml"

_ROLES = ("translation", "judging", "restoration", "profiling")
_MIN_TIERS = 2

# api_key must be exactly one ${VAR} reference — the template holds no keys.
_ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    print(
        "hint: fix config/local.example.yaml; this gate keeps the on-repo "
        "template parseable by LLMPoolConfig with >=2 tiers per role (OL#195)",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main() -> None:
    if not _EXAMPLE_PATH.is_file():
        _fail(f"{_EXAMPLE_PATH} is missing — the on-repo template must exist")

    # src/ layout: make ol_config importable whether or not the package is
    # installed (same bootstrap as scripts/calibrate_m2.7.py).
    _SRC = _REPO_ROOT / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

    try:
        from ol_config.loader import SecurityError, load_config
    except ImportError as exc:
        _fail(f"ol_config is not importable — install the package first: {exc}")

    try:
        config, _glossary = load_config(str(_EXAMPLE_PATH))
    except SecurityError as exc:
        _fail(f"hardcoded key detected in the template: {exc}")
    except Exception as exc:
        _fail(f"LLMPoolConfig rejected the template: {exc}")

    pool = config.llm_pool
    problems: list[str] = []
    for role in _ROLES:
        entries = list(getattr(pool, role, []) or [])
        if len(entries) < _MIN_TIERS:
            problems.append(f"{role}: {len(entries)} tier(s), need >= {_MIN_TIERS}")
        for entry in entries:
            key = entry.api_key
            if not isinstance(key, str) or not _ENV_REF_RE.match(key):
                problems.append(
                    f"{role}/{entry.model}: api_key is not a ${{ENV}} "
                    "reference — literal keys are forbidden in the template"
                )
    if problems:
        _fail("; ".join(problems))

    counts = ", ".join(
        f"{role}={len(getattr(pool, role, []) or [])}" for role in _ROLES
    )
    print(
        "OK: config/local.example.yaml parses via LLMPoolConfig "
        f"({counts}; every api_key is a ${{ENV}} ref)"
    )


if __name__ == "__main__":
    main()
