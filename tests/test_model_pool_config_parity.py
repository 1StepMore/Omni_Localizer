"""Parity regression: canonical `config/default.yaml` pool vs env/init/scenario surfaces.

`config/default.yaml` is the SINGLE SOURCE OF TRUTH for OL's model pool. This
test locks three invariants that drifted apart in OL#94:

1. Every ``${VAR}`` referenced by the canonical default is declared in the
   OL ``.env.example`` — a user copying the example must be able to resolve
   every key the shipped config demands.
2. Every OL in-repo scenario (``scenarios/*.yaml``) that gates on an LLM
   provider key declares those canonical ``${VAR}`` names in its
   ``requires_env_any`` OR group — a tier-2 run must gate on the real keys,
   not stale ones. The AND-only ``requires_env`` list is reserved for
   non-provider prerequisites such as ``MCP_ALLOWED_DIRECTORIES``.
3. The ``ol init`` generated preset (``UNIFIED_POOL_PRESET`` +
   ``PRESET_ENV_VARS``) mirrors the canonical pool exactly: same roles, same
   models/providers/priorities/base URLs, and a declared env var for every
   ``${VAR}`` the pool references.

Given/When/Then: the fixture is the committed canonical config; the action is
a pure parse of the sibling surfaces; the assertion is set-equality against
the canonical vars/pool. No LLM call, no network, deterministic.

Why a regression test: ARK_API_KEY was silently missing from ``.env.example``
and the scenarios while ``ol init`` still wrote the retired mimo/OpenCode
pool, so a fresh ``ol init`` + ``ol doctor`` could not resolve the shipped
default. This test fails on that drift and passes only when all surfaces
agree.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_OL_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_YAML = _OL_ROOT / "config" / "default.yaml"
_ENV_EXAMPLE = _OL_ROOT / ".env.example"
_SCENARIOS_DIR = _OL_ROOT / "scenarios"

_ENV_REF_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

# A scenario that gates on ANY of these is an LLM-keyed scenario and must
# declare the full canonical set in its requires_env_any OR group (the pool
# has two providers, and config/default.yaml reads both). Retired providers
# stay listed so a scenario gating on a retired key is still flagged.
_LLM_KEY_MARKERS = {
    "AMD_API_KEY",
    "ARK_API_KEY",
    "ZHIPU_API_KEY",
    "AGNES_API_KEY",
    "OPENCODE_GO_KEY",
    "OPENAI_API_KEY",
    "MINIMAX_API_KEY",
}

_ROLES = ("translation", "judging", "restoration", "profiling")
_POOL_FIELDS = ("provider", "model", "priority", "role", "api_key", "base_url", "timeout")


def _canonical_pool() -> dict[str, list[dict[str, Any]]]:
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))
    return data["llm_pool"]


def _canonical_env_vars() -> set[str]:
    """Every ``${VAR}`` referenced anywhere in the canonical default."""
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))
    raw = yaml.safe_dump(data)
    return set(_ENV_REF_RE.findall(raw))


def _normalize_role(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: e.get(k) for k in _POOL_FIELDS} for e in entries]


def _declared_env_vars(env_example_text: str) -> set[str]:
    declared: set[str] = set()
    for line in env_example_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name:
            declared.add(name)
    return declared


def _scenario_llm_vars(data: dict[str, Any]) -> set[str]:
    """Every LLM provider key a scenario gates on: AND list ∪ OR group.

    Detection must span both fields. A migrated scenario keeps its provider
    keys only in ``requires_env_any``, so keying on ``requires_env`` alone
    would silently skip it — the vacuity this guard exists to prevent.
    """
    requires = set(data.get("requires_env") or [])
    requires_any = set(data.get("requires_env_any") or [])
    return (requires | requires_any) & _LLM_KEY_MARKERS


def _scenario_env_drift(data: dict[str, Any], canonical: set[str]) -> list[str]:
    """Return drift messages for one LLM-keyed scenario (empty = clean).

    A migrated LLM-keyed scenario declares the full canonical provider set in
    its ``requires_env_any`` OR group. Two failure modes are named distinctly:
    providers still left in the AND list (the pre-migration shape), and an OR
    group missing a canonical key.
    """
    requires = set(data.get("requires_env") or [])
    requires_any = set(data.get("requires_env_any") or [])
    drift: list[str] = []
    providers_in_and = sorted(requires & _LLM_KEY_MARKERS)
    if providers_in_and:
        drift.append(
            "providers still in the AND list (requires_env): "
            f"{providers_in_and} — move them to requires_env_any"
        )
    missing_or = sorted(canonical - requires_any)
    if missing_or:
        drift.append(
            f"OR group (requires_env_any) missing canonical key(s): {missing_or}"
        )
    return drift


# ---------------------------------------------------------------------------
# 1. Canonical ${VAR}s are declared in the OL .env.example
# ---------------------------------------------------------------------------

class TestEnvExampleParity:
    def test_env_example_declares_every_canonical_var(self):
        canonical = _canonical_env_vars()
        declared = _declared_env_vars(_ENV_EXAMPLE.read_text(encoding="utf-8"))
        missing = sorted(canonical - declared)
        assert not missing, (
            f"{_ENV_EXAMPLE.name} is missing canonical vars {missing}; "
            "a user copying the example cannot resolve the shipped default.yaml"
        )

    def test_canonical_vars_are_exactly_the_expected_set(self):
        # Guard against silent pool churn: if the pool gains a provider, the
        # env/scenario/init surfaces must be updated in the same change.
        assert _canonical_env_vars() == {
            "AMD_API_KEY", "ZHIPU_API_KEY",
        }


# ---------------------------------------------------------------------------
# 2. Canonical ${VAR}s are declared in every LLM-keyed OL scenario's
#    requires_env_any OR group
# ---------------------------------------------------------------------------

class TestScenarioEnvParity:
    def _scenario_files(self) -> list[Path]:
        return sorted(_SCENARIOS_DIR.glob("*.yaml"))

    def test_at_least_one_scenario_exists(self):
        assert self._scenario_files(), f"no scenario yaml found in {_SCENARIOS_DIR}"

    def test_every_llm_keyed_scenario_declares_canonical_vars(self):
        canonical = _canonical_env_vars()
        candidates = self._scenario_files()
        offenders: list[str] = []
        examined = 0
        for path in candidates:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not _scenario_llm_vars(data):
                continue
            examined += 1
            drift = _scenario_env_drift(data, canonical)
            if drift:
                offenders.append(f"{path.name}: " + "; ".join(drift))

        # Anti-vacuity: an LLM-keyed guard that examines zero files passes
        # without verifying anything, so recompute the selected set
        # independently and require a non-zero, matching count.
        expected = sum(
            1
            for path in candidates
            if _scenario_llm_vars(yaml.safe_load(path.read_text(encoding="utf-8")))
        )
        assert expected > 0, (
            f"vacuous parity check: none of the {len(candidates)} file(s) in "
            f"{_SCENARIOS_DIR} declare an LLM provider key in "
            "requires_env ∪ requires_env_any"
        )
        assert examined == expected, (
            f"parity check examined {examined} LLM-keyed scenario(s) but "
            f"discovery selected {expected}"
        )
        assert not offenders, (
            "scenario env gate drifted from config/default.yaml:\n  "
            + "\n  ".join(offenders)
        )


# ---------------------------------------------------------------------------
# 3. `ol init` preset mirrors the canonical pool exactly
# ---------------------------------------------------------------------------

class TestInitPresetParity:
    def test_init_preset_roles_match_canonical(self):
        from cli.init import UNIFIED_POOL_PRESET

        assert set(UNIFIED_POOL_PRESET) == set(_canonical_pool()), (
            "`ol init` preset role buckets differ from config/default.yaml"
        )

    def test_init_preset_entries_match_canonical(self):
        from cli.init import UNIFIED_POOL_PRESET

        canonical = _canonical_pool()
        for role in _ROLES:
            assert _normalize_role(UNIFIED_POOL_PRESET[role]) == _normalize_role(
                canonical[role]
            ), f"`ol init` preset for role {role!r} drifted from config/default.yaml"

    def test_preset_env_vars_cover_every_canonical_var(self):
        from cli.init import PRESET_ENV_VARS

        missing = sorted(_canonical_env_vars() - set(PRESET_ENV_VARS))
        assert not missing, (
            f"PRESET_ENV_VARS omits canonical vars {missing}; the `ol init` "
            "export hint would not tell the user which keys to set"
        )

    def test_preset_env_vars_are_exactly_canonical(self):
        from cli.init import PRESET_ENV_VARS

        assert set(PRESET_ENV_VARS) == _canonical_env_vars()


# ---------------------------------------------------------------------------
# 4. Suite-level surfaces (skipped when OL is checked out standalone)
# ---------------------------------------------------------------------------

_SUITE_ROOT = _OL_ROOT.parent
_SUITE_ENV_EXAMPLE = _SUITE_ROOT / ".env.example"
_SUITE_OL_SCENARIOS = (
    _SUITE_ROOT / "scenarios" / "agent-surface",
    _SUITE_ROOT / "scenarios" / "pipeline",
)

_suite_layout = pytest.mark.skipif(
    not _SUITE_ENV_EXAMPLE.exists(),
    reason="suite root not present (OL checked out standalone)",
)


@_suite_layout
class TestSuiteSurfaceParity:
    def test_suite_env_example_declares_canonical_vars(self):
        declared = _declared_env_vars(_SUITE_ENV_EXAMPLE.read_text(encoding="utf-8"))
        missing = sorted(_canonical_env_vars() - declared)
        assert not missing, f"suite .env.example is missing {missing}"

    @staticmethod
    def _is_ol_driven(path: Path) -> bool:
        """Only OL-driving scenarios read OL's model pool.

        agent-surface: ``tool-ol-*`` and the omnibus ``tool-omni_mcp-*``;
        pipeline: every ``pipeline-*`` scenario runs the OL translate stage.
        """
        name = path.name
        if path.parent.name == "pipeline":
            return name.startswith("pipeline-")
        return name.startswith("tool-ol-") or name.startswith("tool-omni_mcp-")

    def test_suite_ol_scenarios_declare_canonical_vars(self):
        canonical = _canonical_env_vars()
        candidates: list[Path] = []
        for directory in _SUITE_OL_SCENARIOS:
            if not directory.exists():
                continue
            candidates.extend(sorted(directory.glob("*.yaml")))
        ol_driven = [path for path in candidates if self._is_ol_driven(path)]

        offenders: list[str] = []
        examined = 0
        for path in ol_driven:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not _scenario_llm_vars(data):
                continue
            examined += 1
            drift = _scenario_env_drift(data, canonical)
            if drift:
                offenders.append(
                    f"{path.relative_to(_SUITE_ROOT)}: " + "; ".join(drift)
                )

        # Anti-vacuity: keying detection on requires_env alone skipped every
        # migrated suite scenario (0 of them examined) while still passing.
        # Recompute the selected set independently and require a match.
        expected = sum(
            1
            for path in ol_driven
            if _scenario_llm_vars(yaml.safe_load(path.read_text(encoding="utf-8")))
        )
        assert expected > 0, (
            f"vacuous parity check: none of the {len(ol_driven)} OL-driven "
            "suite scenario(s) under "
            f"{[str(d.relative_to(_SUITE_ROOT)) for d in _SUITE_OL_SCENARIOS]} "
            "declare an LLM provider key in requires_env ∪ requires_env_any"
        )
        assert examined == expected, (
            f"parity check examined {examined} LLM-keyed suite scenario(s) "
            f"but discovery selected {expected}"
        )
        assert not offenders, (
            "suite OL scenario env gate drifted from config/default.yaml:\n  "
            + "\n  ".join(offenders)
        )
