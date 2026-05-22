"""Stability tracking for LQA scores across attempts."""

from statistics import median


class StabilityTracker:
    """Track score stability across multiple evaluation attempts.

    Records scores per unit and detects instability using variance threshold.
    When variance exceeds threshold, returns median score with Unstable_Score warning.
    """

    def __init__(self, variance_threshold: float = 2.0) -> None:
        """Initialize StabilityTracker.

        Args:
            variance_threshold: Maximum allowed score range (max - min). If exceeded,
                the unit is flagged as unstable. Default is 2.0 points.

        """
        self._scores: dict[str, list[float]] = {}
        self._variance_threshold = variance_threshold

    def record_score(self, unit_id: str, score: float) -> None:
        """Record a score for a unit.

        Args:
            unit_id: Unique identifier for the translation unit.
            score: The LQA score to record.

        """
        if unit_id not in self._scores:
            self._scores[unit_id] = []
        self._scores[unit_id].append(score)

    def check_stability(self, unit_id: str) -> tuple[bool, float]:
        """Check if scores are stable and return the appropriate score.

        Args:
            unit_id: Unique identifier for the translation unit.

        Returns:
            Tuple of (is_stable, final_score).
            If variance > threshold: (False, median score).
            If variance <= threshold: (True, last recorded score).
            If not enough data: (True, last score or 0.0 if no scores).

        """
        scores = self._scores.get(unit_id, [])
        if len(scores) < 2:
            return True, scores[-1] if scores else 0.0

        variance = max(scores) - min(scores)
        if variance > self._variance_threshold:
            return False, median(scores)
        return True, scores[-1]

    def get_warning(self, unit_id: str) -> str | None:
        """Get warning message for an unstable unit.

        Args:
            unit_id: Unique identifier for the translation unit.

        Returns:
            "Unstable_Score" if variance > threshold, None otherwise.

        """
        is_stable, _ = self.check_stability(unit_id)
        return "Unstable_Score" if not is_stable else None

    def get_scores(self, unit_id: str) -> list[float]:
        """Get all recorded scores for a unit.

        Args:
            unit_id: Unique identifier for the translation unit.

        Returns:
            List of recorded scores, empty list if unit not found.

        """
        return list(self._scores.get(unit_id, []))

    def clear(self) -> None:
        """Clear all recorded scores."""
        self._scores.clear()
