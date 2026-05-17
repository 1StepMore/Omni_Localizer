"""Config schema using pydantic."""
import os
import re
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class LLMModelRole(str, Enum):
    """Role for LLM model in the pipeline."""
    TRANSLATION = "translation"
    JUDGING = "judging"
    RESTORATION = "restoration"


def _check_env_vars(api_key: Optional[str]) -> None:
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
    api_key: Optional[str] = Field(None, description="API key. Can also use env var ${VAR} syntax.")
    base_url: Optional[str] = Field(None, description="Custom API endpoint. Can use env var ${VAR} syntax.")
    role: LLMModelRole = Field(..., description="Role: translation, judging, or restoration")

class LLMPoolConfig(BaseModel):
    """LLM model pool configuration."""
    translation: List[LLMModelConfig] = Field(default_factory=list, description="Translation models")
    judging: List[LLMModelConfig] = Field(default_factory=list, description="Judging models")
    restoration: List[LLMModelConfig] = Field(default_factory=list, description="Restoration models")

    @model_validator(mode='after')
    def check_min_models_per_role(self) -> 'LLMPoolConfig':
        for role_field in ('translation', 'judging', 'restoration'):
            models = getattr(self, role_field, [])
            if len(models) < 2:
                raise ValueError(
                    f"'{role_field}' must have at least 2 models (primary + backup), "
                    f"got {len(models)}"
                )
        return self

class ProjectConfig(BaseModel):
    """Main project configuration."""
    project_id: str = Field("default-project", description="Unique project identifier")
    source_lang: str = Field("en", description="Source language code: en, zh, ja, etc.")
    target_lang: str = Field("zh", description="Target language code: zh, en, ja, etc.")
    glossary_path: Optional[str] = Field(None, description="Path to glossary file (CSV/TBX)")
    llm_pool: LLMPoolConfig = Field(..., description="LLM model pool configuration")