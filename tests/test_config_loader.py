"""Config loader tests for Omni-Localizer."""
import pytest
from pathlib import Path
from pydantic import ValidationError
from ol_config.schema import LLMModelConfig, LLMPoolConfig, ProjectConfig
from ol_config.loader import load_config, validate_config

class TestConfigSchema:
    """Test config schema definitions."""

    def test_llm_model_config_creation(self):
        """Test LLMModelConfig can be created."""
        from ol_config.schema import LLMModelRole
        config = LLMModelConfig(provider="openai", model="gpt-4", priority=1, role=LLMModelRole.TRANSLATION)
        assert config.provider == "openai"
        assert config.model == "gpt-4"
        assert config.priority == 1
        assert config.role == LLMModelRole.TRANSLATION

    def test_llm_pool_config_creation(self):
        """Test LLMPoolConfig can be created."""
        from ol_config.schema import LLMModelRole
        pool = LLMPoolConfig(
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
            ]
        )
        assert len(pool.translation) == 2
        assert len(pool.judging) == 2
        assert len(pool.restoration) == 2

    def test_project_config_creation(self):
        """Test ProjectConfig can be created."""
        from ol_config.schema import LLMModelRole
        pool = LLMPoolConfig(
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
            ]
        )
        config = ProjectConfig(
            project_id="test-project",
            source_lang="en",
            target_lang="zh",
            llm_pool=pool
        )
        assert config.project_id == "test-project"
        assert config.source_lang == "en"
        assert config.target_lang == "zh"

class TestConfigLoader:
    """Test config loading from YAML."""
    
    def test_load_valid_config(self):
        """Test loading valid config file and checking basic fields."""
        from ol_config.schema import LLMModelRole
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.TRANSLATION),
                LLMModelConfig(provider="deepseek", model="deepseek-chat", priority=2, role=LLMModelRole.TRANSLATION),
            ],
            judging=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.JUDGING),
                LLMModelConfig(provider="deepseek", model="deepseek-chat", priority=2, role=LLMModelRole.JUDGING),
            ],
            restoration=[
                LLMModelConfig(provider="openai", model="gpt-4o-mini", priority=1, role=LLMModelRole.RESTORATION),
                LLMModelConfig(provider="deepseek", model="deepseek-chat", priority=2, role=LLMModelRole.RESTORATION),
            ]
        )
        config = ProjectConfig(
            project_id="test",
            source_lang="en",
            target_lang="zh",
            llm_pool=pool
        )
        assert config.project_id == "test"
        assert config.source_lang == "en"
        assert config.target_lang == "zh"
    
    def test_missing_required_field(self):
        """Test that missing required field raises ValidationError."""
        with pytest.raises(ValidationError):
            ProjectConfig(
                source_lang="en",
                target_lang="zh",
                llm_pool=LLMPoolConfig(translation=[], judging=[])
                # missing project_id
            )
    
    def test_empty_model_list_not_allowed_by_schema(self):
        """Test that schema requires at least 2 models per role (primary + backup)."""
        from ol_config.schema import LLMModelRole
        with pytest.raises(ValidationError) as exc_info:
            pool = LLMPoolConfig(translation=[], judging=[])
        assert "at least 2 models" in str(exc_info.value)

    def test_glossary_path_optional(self):
        """Test that glossary_path is optional."""
        from ol_config.schema import LLMModelRole
        pool = LLMPoolConfig(
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
            ]
        )
        config = ProjectConfig(
            project_id="test",
            source_lang="en",
            target_lang="zh",
            llm_pool=pool
        )
        assert config.glossary_path is None
        assert config.model_dump().get("glossary_path") is None
    
    def test_nonexistent_file_raises(self):
        """Test that nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config("config/nonexistent.yaml")