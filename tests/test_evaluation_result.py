"""EvaluationResult tests for Omni-Localizer."""
import pytest
from ol_core.dataclass import EvaluationResult

class TestEvaluationResult:
    """Test EvaluationResult dataclass."""

    def test_creation(self):
        """Test EvaluationResult can be created."""
        er = EvaluationResult(
            unit_id="u1",
            scorer_scores={"bleu": 0.85},
            judge_scores={"adequacy": 8.0},
            format_preserved=True,
            format_errors=[],
            warnings=[]
        )
        assert er.unit_id == "u1"
        assert er.scorer_scores == {"bleu": 0.85}
        assert er.judge_scores == {"adequacy": 8.0}

    def test_passed_scorer(self):
        """Test passed_scorer property."""
        er = EvaluationResult(
            unit_id="u1",
            scorer_scores={"bleu": 0.85, "rouge": 0.75},
            judge_scores={},
            format_preserved=True,
            format_errors=[],
            warnings=[]
        )
        assert er.passed_scorer == True  # all >= 0.7

        er_low = EvaluationResult(
            unit_id="u2",
            scorer_scores={"bleu": 0.5},
            judge_scores={},
            format_preserved=True,
            format_errors=[],
            warnings=[]
        )
        assert er_low.passed_scorer == False  # 0.5 < 0.7

    def test_judge_overall_score(self):
        """Test judge_overall_score property."""
        er = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={"adequacy": 8.0, "fluency": 9.0},
            format_preserved=True,
            format_errors=[],
            warnings=[]
        )
        assert er.judge_overall_score == 8.5  # (8.0 + 9.0) / 2

    def test_judge_overall_score_empty(self):
        """Test judge_overall_score with no judge scores."""
        er = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={},
            format_preserved=True,
            format_errors=[],
            warnings=[]
        )
        assert er.judge_overall_score == 0.0

    def test_warnings_and_errors(self):
        """Test warnings and format errors."""
        er = EvaluationResult(
            unit_id="u1",
            scorer_scores={},
            judge_scores={},
            format_preserved=False,
            format_errors=["Missing placeholder", "Tag mismatch"],
            warnings=["Low score", "Term miss"]
        )
        assert len(er.format_errors) == 2
        assert len(er.warnings) == 2