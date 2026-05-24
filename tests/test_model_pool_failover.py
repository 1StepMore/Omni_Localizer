from unittest.mock import MagicMock, patch

import pytest

from ol_config.schema import LLMModelConfig, LLMModelRole, LLMPoolConfig
from ol_pool.router import ModelPool


class TestModelPool:
    @pytest.fixture
    def mock_config(self):
        pool = LLMPoolConfig(
            translation=[
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=1,
                    role=LLMModelRole.TRANSLATION,
                ),
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o",
                    priority=2,
                    role=LLMModelRole.TRANSLATION,
                ),
            ],
            judging=[
                LLMModelConfig(
                    provider="anthropic",
                    model="claude-3-sonnet",
                    priority=1,
                    role=LLMModelRole.JUDGING,
                ),
                LLMModelConfig(
                    provider="anthropic",
                    model="claude-3-opus",
                    priority=2,
                    role=LLMModelRole.JUDGING,
                ),
            ],
            restoration=[
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=1,
                    role=LLMModelRole.RESTORATION,
                ),
                LLMModelConfig(
                    provider="openai",
                    model="gpt-4o-mini",
                    priority=2,
                    role=LLMModelRole.RESTORATION,
                ),
            ],
        )
        return MagicMock(llm_pool=pool)

    @patch("src.ol_pool.router.load_config")
    @patch("src.ol_pool.router.Router")
    def test_model_pool_initializes_router(self, mock_router_class, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        mock_router_class.assert_called_once()
        call_kwargs = mock_router_class.call_args.kwargs
        assert call_kwargs["routing_strategy"] == "simple-shuffle"
        assert call_kwargs["num_retries"] == 2
        assert call_kwargs["timeout"] == 120.0
        assert "fallbacks" in call_kwargs

    @patch("src.ol_pool.router.load_config")
    def test_build_model_list_creates_correct_structure(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        model_list = pool._build_model_list(mock_config.llm_pool)
        translation_models = [m for m in model_list if m["model_name"] == "translation"]
        judging_models = [m for m in model_list if m["model_name"] == "judging"]
        assert len(translation_models) == 2
        assert len(judging_models) == 2
        assert translation_models[0]["litellm_params"]["model"] == "openai/gpt-4o-mini"
        assert judging_models[0]["litellm_params"]["model"] == "anthropic/claude-3-sonnet"

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_translate_returns_placeholder(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        result = await pool.translate("hello", "en", "zh")
        assert result == "placeholder"

    @pytest.mark.asyncio
    @patch("src.ol_pool.router.load_config")
    async def test_judge_returns_placeholder(self, mock_load_config, mock_config):
        mock_load_config.return_value = mock_config
        pool = ModelPool()
        result = await pool.judge("hello", "你好", "en", "zh")
        assert result["score"] == 0
        assert result["reason"] == "placeholder"
