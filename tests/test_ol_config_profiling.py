"""Tests for the PROFILING LLM role (Task 1.1).

Covers:
- LLMModelRole.PROFILING exists and equals "profiling"
- Config without profiling: key loads (backward compat)
- Config with 1 profiling model loads
- Profiling with 0 models is valid (optional)
- Config with profiling AND 0 models in another role fails validation
"""

import pytest
from pydantic import ValidationError

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig


class TestProfilingRole:
    """Tests for the PROFILING enum value."""

    def test_profiling_enum_exists(self):
        """LLMModelRole.PROFILING exists and equals 'profiling'."""
        assert hasattr(LLMModelRole, "PROFILING")
        assert LLMModelRole.PROFILING == "profiling"

    def test_profiling_is_distinct(self):
        """PROFILING is distinct from TRANSLATION, JUDGING, RESTORATION."""
        assert LLMModelRole.PROFILING != LLMModelRole.TRANSLATION
        assert LLMModelRole.PROFILING != LLMModelRole.JUDGING
        assert LLMModelRole.PROFILING != LLMModelRole.RESTORATION


class TestProfilingPoolConfig:
    """Tests for profiling in LLMPoolConfig."""

    def _minimal_valid_pool(self) -> LLMPoolConfig:
        """Create a pool with the minimum 2 models per required role."""
        return LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="anthropic", model="claude-3", priority=2, role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.RESTORATION),
            ],
        )

    def test_no_profiling_still_loads(self):
        """Backward compat: config without profiling key is valid (profiling defaults to [])."""
        pool = self._minimal_valid_pool()
        assert pool.profiling == []

    def test_one_profiling_model_loads(self):
        """A config with 1 profiling model is valid."""
        pool = self._minimal_valid_pool()
        pool.profiling = [
            LLMModelConfig(provider="openai", model="glm-4-flash", priority=1, role=LLMModelRole.PROFILING),
        ]
        assert len(pool.profiling) == 1
        assert pool.profiling[0].role == LLMModelRole.PROFILING

    def test_profiling_zero_models_valid(self):
        """Profiling can have 0 models (its optional)."""
        pool = self._minimal_valid_pool()
        pool.profiling = []
        assert pool.profiling == []

    def test_profiling_multiple_models_valid(self):
        """A config with 2+ profiling models is valid."""
        pool = self._minimal_valid_pool()
        pool.profiling = [
            LLMModelConfig(provider="openai", model="glm-4-flash", priority=1, role=LLMModelRole.PROFILING),
            LLMModelConfig(provider="openai", model="agnes-2.0-flash", priority=2, role=LLMModelRole.PROFILING),
        ]
        assert len(pool.profiling) == 2

    def test_translation_still_requires_two(self):
        """Validator still enforces >=2 for translation even with profiling present."""
        with pytest.raises(ValidationError, match="at least 2 models"):
            LLMPoolConfig(
                translation=[
                    LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.TRANSLATION),
                    # only 1 model — should fail
                ],
                judging=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.JUDGING),
                    LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.JUDGING),
                ],
                restoration=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.RESTORATION),
                    LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.RESTORATION),
                ],
                profiling=[
                    LLMModelConfig(provider="openai", model="glm-4-flash", priority=1, role=LLMModelRole.PROFILING),
                ],
            )

    def test_judging_still_requires_two(self):
        """Validator still enforces >=2 for judging even with profiling present."""
        with pytest.raises(ValidationError, match="at least 2 models"):
            LLMPoolConfig(
                translation=[
                    LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.TRANSLATION),
                    LLMModelConfig(provider="anthropic", model="claude-3", priority=2, role=LLMModelRole.TRANSLATION),
                ],
                judging=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.JUDGING),
                    # only 1 model — should fail
                ],
                restoration=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.RESTORATION),
                    LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.RESTORATION),
                ],
                profiling=[
                    LLMModelConfig(provider="openai", model="glm-4-flash", priority=1, role=LLMModelRole.PROFILING),
                ],
            )

    def test_restoration_still_requires_two(self):
        """Validator still enforces >=2 for restoration even with profiling present."""
        with pytest.raises(ValidationError, match="at least 2 models"):
            LLMPoolConfig(
                translation=[
                    LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.TRANSLATION),
                    LLMModelConfig(provider="anthropic", model="claude-3", priority=2, role=LLMModelRole.TRANSLATION),
                ],
                judging=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.JUDGING),
                    LLMModelConfig(provider="anthropic", model="claude-3-haiku", priority=2, role=LLMModelRole.JUDGING),
                ],
                restoration=[
                    LLMModelConfig(provider="openai", model="gpt-4-mini", priority=1, role=LLMModelRole.RESTORATION),
                    # only 1 model — should fail
                ],
                profiling=[
                    LLMModelConfig(provider="openai", model="glm-4-flash", priority=1, role=LLMModelRole.PROFILING),
                ],
            )
