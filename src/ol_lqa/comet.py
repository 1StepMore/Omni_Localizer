"""COMETService for XCOMET reference-free quality scoring with MQM error detection."""
import asyncio
from typing import Any

from ol_core.dataclass import EvaluationResult


class COMETService:
    DEFAULT_MODEL = "Unbabel/XCOMET-XL"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None
        self._model_path: str | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from comet import download_model, load_from_checkpoint

            self._model_path = download_model(self._model_name)
            self._model = load_from_checkpoint(self._model_path)

        return self._model

    async def score_xcomet(
        self,
        source: str,
        target: str,
        source_lang: str,
        target_lang: str,
    ) -> float:
        loop = asyncio.get_event_loop()

        def _score_sync() -> float:
            model = self._ensure_model()

            data = [{"src": source, "mt": target}]
            output = model.predict(data, batch_size=1)

            return output.scores[0] if output.scores else 0.0

        return float(await loop.run_in_executor(None, _score_sync))

    def get_mqm_spans(self, source: str, target: str) -> list[dict[str, Any]]:
        model = self._ensure_model()

        data = [{"src": source, "mt": target}]
        output = model.predict(data, batch_size=1)

        error_spans = []
        if hasattr(output, "metadata") and output.metadata:
            metadata = output.metadata[0] if output.metadata else {}
            for span in metadata.get("error_spans", []):
                error_spans.append(
                    {
                        "start": span.get("start", 0),
                        "end": span.get("end", 0),
                        "text": span.get("text", ""),
                        "severity": span.get("severity", "minor"),
                        "confidence": span.get("confidence", 0.0),
                    },
                )

        return error_spans

    async def score_and_evaluate(
        self,
        source: str,
        target: str,
        unit_id: str,
        source_lang: str,
        target_lang: str,
    ) -> EvaluationResult:
        score = await self.score_xcomet(source, target, source_lang, target_lang)
        mqm_spans = self.get_mqm_spans(source, target)

        return EvaluationResult(
            unit_id=unit_id,
            scorer_scores={"xcomet": score},
            judge_scores={},
            format_preserved=True,
            format_errors=[],
            warnings=[f"MQM spans: {len(mqm_spans)} errors detected"]
            if mqm_spans
            else [],
            mqm_spans=mqm_spans,
        )

    @property
    def model_name(self) -> str:
        return self._model_name
