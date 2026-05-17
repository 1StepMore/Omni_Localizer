"""Tests for model pool schema validation."""
import os
import pytest
from pydantic import ValidationError
from ol_config.schema import LLMModelConfig, LLMPoolConfig, ProjectConfig, LLMModelRole


class TestLLMModelRole:
    """Test LLMModelRole enum."""

    def test_role_values(self):
        """Test enum has correct values."""
        assert LLMModelRole.TRANSLATION.value == "translation"
        assert LLMModelRole.JUDGING.value == "judging"
        assert LLMModelRole.RESTORATION.value == "restoration"


class TestLLMModelConfig:
    """Test LLMModelConfig validation."""

    def test_valid_model_config(self):
        """Test creating valid model config with role."""
        config = LLMModelConfig(
            provider="openai",
            model="gpt-4o-mini",
            priority=1,
            role=LLMModelRole.TRANSLATION
        )
        assert config.provider == "openai"
        assert config.role == LLMModelRole.TRANSLATION

    def test_api_key_env_var_exists(self):
        """Test that existing env var in api_key passes validation."""
        os.environ["MY_API_KEY"] = "secret123"
        config = LLMModelConfig(
            provider="openai",
            model="gpt-4",
            priority=1,
            api_key="${MY_API_KEY}",
            role=LLMModelRole.TRANSLATION
        )
        assert config.api_key == "${MY_API_KEY}"
        del os.environ["MY_API_KEY"]


class TestLLMPoolConfig:
    """Test LLMPoolConfig validation."""

    def test_valid_pool_with_two_models_per_role(self):
        """Test pool with 2 models per role passes validation."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="gpt-4o", priority=2, role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="anthropic", model="claude-3-sonnet", priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="anthropic", model="claude-3-opus", priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=2, role=LLMModelRole.RESTORATION),
            ]
        )
        assert len(pool.translation) == 2
        assert len(pool.judging) == 2
        assert len(pool.restoration) == 2

    def test_pool_with_only_one_translation_model_fails(self):
        """Test that pool with only 1 translation model raises error."""
        with pytest.raises(ValidationError) as exc_info:
            LLMPoolConfig(
                translation=[
                    LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.TRANSLATION),
                ],
                judging=[
                    LLMModelConfig(provider="anthropic", model="claude-3-sonnet", priority=1, role=LLMModelRole.JUDGING),
                    LLMModelConfig(provider="anthropic", model="claude-3-opus", priority=2, role=LLMModelRole.JUDGING),
                ]
            )
        assert "translation" in str(exc_info.value)
        assert "at least 2 models" in str(exc_info.value)

    def test_pool_with_empty_list_fails(self):
        """Test that empty model list raises error."""
        with pytest.raises(ValidationError):
            LLMPoolConfig(
                translation=[],
                judging=[
                    LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.JUDGING),
                    LLMModelConfig(provider="openai", model="gpt-4", priority=2, role=LLMModelRole.JUDGING),
                ]
            )


class TestProjectConfigWithPool:
    """Test ProjectConfig with model pool validation."""

    def test_valid_project_config(self):
        """Test creating project config with valid pool."""
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="openai", model="gpt-4o", priority=2, role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="anthropic", model="claude-3-sonnet", priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=2, role=LLMModelRole.RESTORATION),
            ]
        )
        config = ProjectConfig(
            project_id="test-project",
            source_lang="en",
            target_lang="zh",
            llm_pool=pool
        )
        assert config.project_id == "test-project"
        assert len(config.llm_pool.translation) == 2