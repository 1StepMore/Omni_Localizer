"""Regression tests for the config/local.example.yaml template gate (OL#195).

`config/local.yaml` — the pool's single source of truth — is gitignored, so
the example file is the only on-repo template. The CI step runs
`scripts/check_local_example.py`; these tests lock the same invariants
hermetically so `make test` catches schema drift even without CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_OL_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE = _OL_ROOT / "config" / "local.example.yaml"

_ROLES = ("translation", "judging", "restoration", "profiling")

# api_key must be exactly one ${VAR} reference — the template holds no keys.
_ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def _example_data() -> dict:
    return yaml.safe_load(_EXAMPLE.read_text(encoding="utf-8"))


class TestLocalExampleTemplate:
    def test_template_exists(self):
        assert _EXAMPLE.is_file(), (
            "config/local.example.yaml is the only on-repo pool template (OL#195)"
        )

    def test_parses_through_real_loader(self):
        # The REAL loader: schema validation + hardcoded-key SecurityError scan,
        # exactly as a user's config/local.yaml would be loaded.
        from ol_config.loader import load_config

        config, _glossary = load_config(str(_EXAMPLE))
        assert config.project_id

    def test_every_role_has_at_least_two_tiers(self):
        pool = _example_data()["llm_pool"]
        for role in _ROLES:
            assert len(pool[role]) >= 2, (
                f"{role} needs >= 2 tiers (OL#195 template homogeneity)"
            )

    def test_every_api_key_is_env_reference(self):
        pool = _example_data()["llm_pool"]
        for role in _ROLES:
            for entry in pool[role]:
                assert _ENV_REF_RE.match(str(entry["api_key"])), (
                    f"{role}/{entry['model']}: api_key must be a "
                    "${ENV} reference, never a literal key"
                )

    def test_no_loopback_addresses_in_template(self):
        # 禁区 (OL#195): single-machine addresses must not appear anywhere in
        # the tracked template — not even in comments — because a clone would
        # inherit an endpoint that only resolves on one machine.
        text = _EXAMPLE.read_text(encoding="utf-8")
        assert "127.0.0.1" not in text
        assert "localhost" not in text
