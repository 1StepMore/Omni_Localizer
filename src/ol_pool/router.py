import os
import re
from typing import Any

from litellm import Router

from ol_config.loader import load_config
from ol_config.schema import LLMPoolConfig
from ol_logging.core import get_logger

_logger = get_logger("pool")


def _resolve_env_vars(value: str) -> str:
    if value is None:
        return None
    def replacer(m):
        env_val = os.environ.get(m.group(1))
        if env_val is None:
            raise ValueError(f"Environment variable '{m.group(1)}' not set - cannot resolve config value")
        return env_val
    return re.sub(r'\$\{([^}]+)\}', replacer, value)


class ModelPool:
    def __init__(self, config_path: str = "config/default.yaml"):
        config = load_config(config_path)
        self._router = Router(
            model_list=self._build_model_list(config.llm_pool),
            routing_strategy="simple-shuffle",
            num_retries=2,
            timeout=30,
        )

    def _build_model_list(self, pool: LLMPoolConfig) -> list[dict]:
        model_list = []
        for role in ("translation", "judging", "restoration"):
            for model in getattr(pool, role, []):
                litellm_params = {
                    "model": f"{model.provider}/{model.model}",
                }
                if model.api_key:
                    litellm_params["api_key"] = _resolve_env_vars(model.api_key)
                if model.base_url:
                    litellm_params["base_url"] = _resolve_env_vars(model.base_url)
                model_list.append(
                    {
                        "model_name": role,
                        "litellm_params": litellm_params,
                        "rpm": 500,
                    },
                )
        return model_list

    async def translate(
        self, text: str, source_lang: str, target_lang: str,
        context: dict | str | None = None,
    ) -> str:
        _logger.debug(f"Translation request: {len(text)} chars, {source_lang}→{target_lang}")
        _logger.debug("Model selected: translation")

        if isinstance(context, str):
            prompt = context
        else:
            prompt_parts = [f"Translate from {source_lang} to {target_lang}: {text}"]
            if context:
                tm_matches = context.get("tm_matches", [])
                glossary_terms = context.get("glossary_terms", [])
                if tm_matches:
                    top_tm = tm_matches[:3]
                    tm_lines = "\n".join(
                        f"- {m.get('source', '')} → {m.get('target', '')}"
                        for m in top_tm
                    )
                    prompt_parts.insert(0, f"Translation Memory (top {len(top_tm)} matches):\n{tm_lines}")
                if glossary_terms:
                    top_glossary = glossary_terms[:5]
                    glossary_lines = "\n".join(
                        f"- {g.get('source', '')} → {g.get('target', '')}"
                        for g in top_glossary
                    )
                    prompt_parts.insert(0, f"Glossary (top {len(top_glossary)} terms):\n{glossary_lines}")
            prompt = "\n\n".join(prompt_parts)

        try:
            response = await self._router.acompletion(
                model="translation",
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.0,
            )
            translated = response.choices[0].message.content
            _logger.debug(f"Translation response: {len(translated)} chars")
            return translated
        except Exception as e:
            _logger.error(f"Translation failed: {e}")
            raise

    async def judge(
        self, source: str, target: str, source_lang: str, target_lang: str,
        glossary: dict[str, Any] | None = None,
    ) -> dict:
        terminology_section = ""
        if glossary:
            terms = ", ".join(f"{k} → {v}" for k, v in glossary.items())
            terminology_section = f"\nTerminology: {terms}"
        prompt = f"""Evaluate translation quality:

Source ({source_lang}): {source}
Target ({target_lang}): {target}{terminology_section}

Rate the translation on a scale of 0-100 for:
- Accuracy (30%)
- Fluency (30%)
- Adequacy (40%)

Return a JSON object with:
{{"score": <int 0-100>, "reason": "<brief explanation>"}}
Only return valid JSON, nothing else."""

        response = await self._router.acompletion(
            model="judging",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        import json
        content = response.choices[0].message.content.strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            score = 50
            reason = content[:200] if content else "Parse failed"
            result = {"score": score, "reason": reason}
        return result
