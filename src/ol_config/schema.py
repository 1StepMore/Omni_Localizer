"""Config schema using pydantic."""
import os
import re
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class LLMModelRole(str, Enum):
    """Role for LLM model in the pipeline."""

    TRANSLATION = "translation"
    JUDGING = "judging"
    RESTORATION = "restoration"


def _check_env_vars(api_key: str | None) -> None:
    if api_key is None:
        return
    env_vars = re.findall(r'\$\{([^}]+)\}', api_key)
    for var in env_vars:
        if var not in os.environ:
            raise ValueError(f"Environment variable '{var}' referenced in api_key but not set")


class LLMModelConfig(BaseModel):
    provider: str = Field(..., description="LLM provider: openai, anthropic, deepseek, etc.")
    model: str = Field(..., description="Model name: gpt-4, claude-3-sonnet, etc.")
    priority: int = Field(1, ge=1, description="Priority (1=highest). Lower number = higher priority.")
    api_key: str | None = Field(None, description="API key. Can also use env var ${VAR} syntax.")
    base_url: str | None = Field(None, description="Custom API endpoint. Can use env var ${VAR} syntax.")
    role: LLMModelRole = Field(..., description="Role: translation, judging, or restoration")
    timeout: float | None = Field(60.0, description="Timeout in seconds for this model. Defaults to 60s.")
    requests_per_minute: int = Field(
        500, ge=1,
        description=(
            "Per-deployment requests-per-minute cap forwarded to litellm Router. "
            "Used as a routing weight by default; for hard 429 enforcement, "
            "the Router must be initialized with enforce_model_rate_limits=True. "
            "Set this to your provider's actual RPM (e.g. NVIDIA free tier = 40) "
            "to avoid burning quota on retry storms. Default 500 preserves the "
            "legacy hardcoded value."
        ),
    )

    @model_validator(mode='after')
    def validate_env_vars(self) -> 'LLMModelConfig':
        _check_env_vars(self.api_key)
        _check_env_vars(self.base_url)
        return self

class LLMPoolConfig(BaseModel):
    """LLM model pool configuration."""

    translation: list[LLMModelConfig] = Field(default_factory=list, description="Translation models")
    judging: list[LLMModelConfig] = Field(default_factory=list, description="Judging models")
    restoration: list[LLMModelConfig] = Field(default_factory=list, description="Restoration models")

    @model_validator(mode='after')
    def check_min_models_per_role(self) -> 'LLMPoolConfig':
        for role_field in ('translation', 'judging', 'restoration'):
            models = getattr(self, role_field, [])
            if len(models) < 2:
                raise ValueError(
                    f"'{role_field}' must have at least 2 models (primary + backup), "
                    f"got {len(models)}",
                )
        return self

class ProjectConfig(BaseModel):
    """Main project configuration."""

    project_id: str = Field("default-project", description="Unique project identifier")
    source_lang: str = Field("en", description="Source language code: en, zh, ja, etc.")
    target_lang: str = Field("zh", description="Target language code: zh, en, ja, etc.")
    glossary_path: str | None = Field(None, description="Path to glossary file (CSV/TBX)")
    llm_pool: LLMPoolConfig = Field(..., description="LLM model pool configuration")
    enable_lqa: bool = Field(False, description="Auto-invoke LQA judge with retry in main pipeline")
    lqa_threshold: float = Field(7.0, description="LQA judge pass threshold (0-10)")
    lqa_max_retries: int = Field(2, description="Max LQA retries (best-of-N strategy)")
    # A3 — slim-pipeline-hardening
    cache_system_prompt: bool = Field(
        True,
        description=(
            "Cache LLM completions in an in-process LRU keyed by "
            "(model, prompt_hash, temperature). Disabled automatically when "
            "temperature != 0. Re-run optimization; no first-run speedup."
        ),
    )
    max_input_size_mb: int = Field(50, ge=1, description="Reject input files larger than this (MB)")
    max_xliff_concurrent: int = Field(20, ge=1, description="Max concurrent in-flight trans-unit translations in XLIFF path")
    max_md_concurrent: int = Field(5, ge=1, description="Max concurrent in-flight trans-unit translations in MD path. Set to 1 to force the serial shield+translate path (1 translate + 1 judge call instead of per-unit calls); dramatically faster for large docs with slow judge models.")
