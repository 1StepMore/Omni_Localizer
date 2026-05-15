from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

class ChannelType(Enum):
    MD = "md"
    XLIFF = "xliff"

@dataclass
class TranslationUnit:
    unit_id: str
    source_text: str
    target_text: Optional[str] = None
    shield_map: Dict[str, str] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

@dataclass
class TranslationContext:
    file_path: str
    channel_type: ChannelType
    original_full_text: str
    units: List[TranslationUnit] = field(default_factory=list)
    glossary: Dict[str, str] = field(default_factory=dict)
    config: Dict = field(default_factory=dict)

    def get_unit_by_id(self, unit_id: str) -> Optional[TranslationUnit]:
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        return None

    def to_json(self) -> dict:
        return {
            "file_path": self.file_path,
            "channel_type": self.channel_type.value,
            "original_full_text": self.original_full_text,
            "units": [
                {
                    "unit_id": u.unit_id,
                    "source_text": u.source_text,
                    "target_text": u.target_text,
                    "shield_map": u.shield_map,
                    "metadata": u.metadata
                }
                for u in self.units
            ],
            "glossary": self.glossary,
            "config": self.config
        }

    @classmethod
    def from_json(cls, data: dict) -> "TranslationContext":
        return cls(
            file_path=data["file_path"],
            channel_type=ChannelType(data["channel_type"]),
            original_full_text=data["original_full_text"],
            units=[TranslationUnit(**u) for u in data["units"]],
            glossary=data.get("glossary", {}),
            config=data.get("config", {})
        )

@dataclass
class RepairContext:
    unit_id: str
    shield_map: Dict[str, str]
    original_text: str
    anchor_words: List[str] = field(default_factory=list)
    max_retries: int = 3

@dataclass
class EvaluationResult:
    unit_id: str
    scorer_scores: Dict[str, float] = field(default_factory=dict)
    judge_scores: Dict[str, float] = field(default_factory=dict)
    format_preserved: bool = True
    format_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def passed_scorer(self) -> bool:
        return all(score >= 0.7 for score in self.scorer_scores.values())

    @property
    def judge_overall_score(self) -> float:
        if not self.judge_scores:
            return 0.0
        return sum(self.judge_scores.values()) / len(self.judge_scores)