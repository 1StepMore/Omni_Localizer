from litellm import Router

from ol_config.loader import load_config
from ol_config.schema import LLMPoolConfig, LLMModelConfig


class ModelPool:
    def __init__(self, config_path: str = "config/default.yaml"):
        config = load_config(config_path)
        self._router = Router(
            model_list=self._build_model_list(config.llm_pool),
            routing_strategy="simple-shuffle",
            num_retries=1,
            timeout=3,
        )

    def _build_model_list(self, pool: LLMPoolConfig) -> list[dict]:
        model_list = []
        for role in ("translation", "judging"):
            for model in getattr(pool, role, []):
                litellm_params = {
                    "model": f"{model.provider}/{model.model}",
                }
                if model.api_key:
                    litellm_params["api_key"] = model.api_key
                model_list.append(
                    {
                        "model_name": role,
                        "litellm_params": litellm_params,
                        "rpm": 500,
                    }
                )
        return model_list

    async def translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> str:
        response = await self._router.acompletion(
            model="translation",
            messages=[
                {
                    "role": "user",
                    "content": f"Translate from {source_lang} to {target_lang}: {text}"
                }
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content

    async def judge(
        self, source: str, target: str, source_lang: str, target_lang: str
    ) -> dict:
        prompt = f"""Evaluate translation quality:

Source ({source_lang}): {source}
Target ({target_lang}): {target}

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