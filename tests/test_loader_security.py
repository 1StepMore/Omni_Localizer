"""FIX-#24: hardcoded API key detector in ol_config.loader.

Round 8 (2026-06-17) regression tests. Validates that load_config()
rejects any api_key field whose value matches a known secret pattern
without being a ${ENV_VAR} interpolation, AND that the documented
OL_ALLOW_HARDCODED_KEYS=1 escape hatch works for local development.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make src/ importable for direct invocation
_OL_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_OL_SRC) not in sys.path:
    sys.path.insert(0, str(_OL_SRC))

from ol_config.loader import (  # noqa: E402
    SecurityError,
    _check_for_hardcoded_secrets,
    _HARDCODED_KEY_PATTERNS,
    _is_env_ref,
    load_config,
)


class TestIsEnvRef:
    def test_env_ref_braced(self):
        assert _is_env_ref("${MY_KEY}")

    def test_env_ref_with_underscore_and_digits(self):
        assert _is_env_ref("${NVIDIA_NIM_API_KEY}")

    def test_not_env_ref_plain_string(self):
        assert not _is_env_ref("just-a-string")

    def test_not_env_ref_partial_braces(self):
        assert not _is_env_ref("${MISSING_CLOSE")
        assert not _is_env_ref("MISSING_OPEN}")


class TestHardcodedSecretPatterns:
    """Verify all 4 known patterns are present."""

    def test_sk_prefix_present(self):
        assert any("sk-" in p.pattern for p in _HARDCODED_KEY_PATTERNS)

    def test_nvapi_prefix_present(self):
        assert any("nvapi-" in p.pattern for p in _HARDCODED_KEY_PATTERNS)

    def test_gsk_prefix_present(self):
        assert any("gsk_" in p.pattern for p in _HARDCODED_KEY_PATTERNS)

    def test_zhipu_hex_dot_present(self):
        # Zhipu MiniMax style: hex.hex
        assert any(r"\.[A-Za-z0-9" in p.pattern for p in _HARDCODED_KEY_PATTERNS)


def _clean_pool() -> dict:
    """Build a clean (env-var only) llm_pool dict."""
    return {
        "translation": [
            {"provider": "openai", "model": "gpt-4", "priority": 1,
             "role": "translation", "api_key": "${OPENAI_API_KEY}"},
            {"provider": "openai", "model": "claude-3", "priority": 2,
             "role": "translation", "api_key": "${ANTHROPIC_API_KEY}"},
        ],
        "judging": [
            {"provider": "openai", "model": "gpt-4", "priority": 1,
             "role": "judging", "api_key": "${OPENAI_API_KEY}"},
            {"provider": "openai", "model": "claude-3", "priority": 2,
             "role": "judging", "api_key": "${ANTHROPIC_API_KEY}"},
        ],
        "restoration": [
            {"provider": "openai", "model": "gpt-4", "priority": 1,
             "role": "restoration", "api_key": "${OPENAI_API_KEY}"},
            {"provider": "openai", "model": "claude-3", "priority": 2,
             "role": "restoration", "api_key": "${ANTHROPIC_API_KEY}"},
        ],
    }


class TestCheckForHardcodedSecretsClean:
    """Configs that should NOT trigger detection (env refs only)."""

    def test_all_env_refs_clean(self):
        data = {"llm_pool": _clean_pool()}
        assert _check_for_hardcoded_secrets(data) == []

    def test_none_api_key_clean(self):
        data = {"llm_pool": {"translation": [
            {"provider": "openai", "model": "gpt-4", "priority": 1,
             "role": "translation", "api_key": None},
        ]}}
        assert _check_for_hardcoded_secrets(data) == []

    def test_missing_llm_pool_clean(self):
        assert _check_for_hardcoded_secrets({}) == []
        assert _check_for_hardcoded_secrets({"llm_pool": None}) == []


class TestCheckForHardcodedSecretsDetection:
    """Configs that MUST trigger detection."""

    def test_sk_literal_detected(self):
        data = {"llm_pool": {"translation": [
            {"provider": "openai", "model": "gpt-4", "priority": 1,
             "role": "translation",
             "api_key": "sk-TEST_PLACEHOLDER_KEY_DO_NOT_USE_REAL_OPENAI_API_KEY"},
        ]}}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 1
        assert "translation/gpt-4" in findings[0]

    def test_nvapi_literal_detected(self):
        data = {"llm_pool": {"translation": [
            {"provider": "openai", "model": "deepseek", "priority": 1,
             "role": "translation",
             "api_key": "nvapi-TEST_PLACEHOLDER_KEY_DO_NOT_USE_REAL_NVIDIA_NIM_KEY"},
        ]}}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 1
        assert "translation/deepseek" in findings[0]

    def test_zhipu_hex_literal_detected(self):
        data = {"llm_pool": {"translation": [
            {"provider": "openai", "model": "glm-4-flash", "priority": 1,
             "role": "translation",
             "api_key": "0123456789abcdef0123456789abcdef.aaaaaaaaaaaaaaaaaaaa"},
        ]}}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 1
        assert "translation/glm-4-flash" in findings[0]

    def test_multiple_findings_reported(self):
        data = {"llm_pool": {
            "translation": [
                {"provider": "openai", "model": "a", "priority": 1,
                 "role": "translation",
                 "api_key": "sk-TEST_PLACEHOLDER_PATTERN_A_OPENAI_DUMMY_VALUE"},
                {"provider": "openai", "model": "b", "priority": 2,
                 "role": "translation",
                 "api_key": "nvapi-TEST_PLACEHOLDER_PATTERN_B_NVIDIA_DUMMY_VALUE"},
            ],
            "judging": [
                {"provider": "openai", "model": "c", "priority": 1,
                 "role": "judging",
                 "api_key": "0123456789abcdef0123456789abcdef.aaaaaaaaaaaaaaaaaaaa"},
            ],
        }}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 3

    def test_judging_and_restoration_roles_also_scanned(self):
        data = {"llm_pool": {
            "judging": [
                {"provider": "openai", "model": "x", "priority": 1,
                 "role": "judging",
                 "api_key": "sk-TEST_PLACEHOLDER_PATTERN_C_JUDGE_DUMMY_VALUE"},
                {"provider": "openai", "model": "y", "priority": 2,
                 "role": "judging", "api_key": "${OK}"},
            ],
            "restoration": [
                {"provider": "openai", "model": "x", "priority": 1,
                 "role": "restoration",
                 "api_key": "sk-TEST_PLACEHOLDER_PATTERN_D_RESTORATION_DUMMY_VALUE"},
                {"provider": "openai", "model": "y", "priority": 2,
                 "role": "restoration", "api_key": "${OK}"},
            ],
            "translation": [
                {"provider": "openai", "model": "x", "priority": 1,
                 "role": "translation", "api_key": "${OK}"},
                {"provider": "openai", "model": "y", "priority": 2,
                 "role": "translation", "api_key": "${OK}"},
            ],
        }}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 2
        assert any("judging/x" in f for f in findings)
        assert any("restoration/x" in f for f in findings)

    def test_findings_preview_does_not_leak_full_key(self):
        """The error message must NOT echo the full key (preview only)."""
        secret = "sk-" + "A" * 50
        data = {"llm_pool": {"translation": [
            {"provider": "openai", "model": "x", "priority": 1,
             "role": "translation", "api_key": secret},
        ]}}
        findings = _check_for_hardcoded_secrets(data)
        assert len(findings) == 1
        assert secret not in findings[0], (
            f"Full key leaked into finding message: {findings[0]}"
        )
        assert findings[0].startswith("translation/x")


_VALID_POOL_YAML = """\
project_id: "test-{tag}"
source_lang: "en"
target_lang: "zh"
max_xliff_concurrent: 5
llm_pool:
  translation:
    - provider: "openai"
      model: "gpt-4"
      priority: 1
      role: "translation"
      api_key: "{bad_or_env}"
    - provider: "openai"
      model: "claude"
      priority: 2
      role: "translation"
      api_key: "${{ANTHROPIC_API_KEY}}"
  judging:
    - provider: "openai"
      model: "gpt-4"
      priority: 1
      role: "judging"
      api_key: "${{OPENAI_API_KEY}}"
    - provider: "openai"
      model: "claude"
      priority: 2
      role: "judging"
      api_key: "${{ANTHROPIC_API_KEY}}"
  restoration:
    - provider: "openai"
      model: "gpt-4"
      priority: 1
      role: "restoration"
      api_key: "${{OPENAI_API_KEY}}"
    - provider: "openai"
      model: "claude"
      priority: 2
      role: "restoration"
      api_key: "${{ANTHROPIC_API_KEY}}"
"""


class TestLoadConfigSecurityIntegration:
    """End-to-end: load_config() must raise SecurityError on bad yaml."""

    def _make_yaml(self, tmp_path: Path, *, tag: str, api_key_value: str) -> Path:
        bad = tmp_path / f"bad_{tag}.yaml"
        bad.write_text(
            _VALID_POOL_YAML.format(tag=tag, bad_or_env=api_key_value)
        )
        return bad

    def test_load_config_rejects_hardcoded_key(self, tmp_path, monkeypatch):
        import os
        monkeypatch.delenv("OL_ALLOW_HARDCODED_KEYS", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        bad = self._make_yaml(
            tmp_path, tag="reject",
            api_key_value="sk-TEST_PLACEHOLDER_KEY_DO_NOT_USE_REAL_OPENAI_API_KEY",
        )
        with pytest.raises(SecurityError) as exc:
            load_config(bad)
        msg = str(exc.value)
        assert "translation/gpt-4" in msg
        assert "${ENV_VAR}" in msg
        # The full leaked key must not appear in the error
        assert "sk-TEST_PLACEHOLDER_KEY_DO_NOT_USE_REAL_OPENAI_API_KEY" not in msg

    def test_load_config_accepts_env_refs(self, tmp_path):
        import os
        os.environ["ANTHROPIC_API_KEY"] = "test-anthropic"
        os.environ["OPENAI_API_KEY"] = "test-openai"
        ok = self._make_yaml(
            tmp_path, tag="accept",
            api_key_value="${OPENAI_API_KEY}",
        )
        config, _ = load_config(ok)
        assert config.project_id == "test-accept"

    def test_opt_out_allows_hardcoded_keys_for_local_dev(self, tmp_path, monkeypatch):
        """OL_ALLOW_HARDCODED_KEYS=1 is a documented escape hatch for
        gitignored local.yaml used during real-LLM local development.
        With it set, load_config() must accept hardcoded literals."""
        monkeypatch.setenv("OL_ALLOW_HARDCODED_KEYS", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
        bad = self._make_yaml(
            tmp_path, tag="optout",
            api_key_value="sk-TEST_PLACEHOLDER_OPTOUT_DEMO_VALUE_FOR_LOCAL_DEV",
        )
        config, _ = load_config(bad)  # must NOT raise
        assert config.project_id == "test-optout"

    def test_opt_out_default_is_off(self, tmp_path):
        """Without OL_ALLOW_HARDCODED_KEYS=1, the check must still fire."""
        import os
        os.environ.pop("OL_ALLOW_HARDCODED_KEYS", None)
        os.environ["ANTHROPIC_API_KEY"] = "test-anthropic"
        os.environ["OPENAI_API_KEY"] = "test-openai"
        bad = self._make_yaml(
            tmp_path, tag="strict",
            api_key_value="sk-TEST_PLACEHOLDER_STRICT_MODE_DEMO_VALUE",
        )
        with pytest.raises(SecurityError):
            load_config(bad)

    def test_default_yaml_passes_security_check(self):
        """The committed default.yaml (after round 8 fix) must load cleanly.

        Only runs if required env vars are set; otherwise the Pydantic
        _check_env_vars validator emits a warning (not error) — but the
        config may still fail at runtime without credentials. Skip in that
        case.
        """
        import os
        required = ["ZHIPU_API_KEY", "AGNES_API_KEY", "NVIDIA_NIM_API_KEY",
                    "OPENCODE_GO_KEY"]
        if not all(os.environ.get(v) for v in required):
            pytest.skip("env vars not set; cannot run default.yaml end-to-end")

        default_yaml = (
            Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        )
        if not default_yaml.exists():
            pytest.skip("default.yaml not found")
        load_config(default_yaml)  # must not raise SecurityError