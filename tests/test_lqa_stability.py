"""Tests for LQA stability tracking."""

import pytest

from ol_lqa.stability import StabilityTracker


class TestStabilityTracker:
    """Tests for StabilityTracker class."""

    def test_record_and_retrieve_score(self) -> None:
        """Test basic score recording and retrieval."""
        tracker = StabilityTracker()
        tracker.record_score("unit1", 85.0)
        tracker.record_score("unit1", 87.0)

        scores = tracker.get_scores("unit1")
        assert scores == [85.0, 87.0]

    def test_single_score_is_stable(self) -> None:
        """Test that a single score is considered stable."""
        tracker = StabilityTracker()
        tracker.record_score("unit1", 90.0)

        is_stable, final_score = tracker.check_stability("unit1")
        assert is_stable is True
        assert final_score == 90.0

    def test_no_scores_returns_zero(self) -> None:
        """Test that missing unit returns stable with zero score."""
        tracker = StabilityTracker()

        is_stable, final_score = tracker.check_stability("nonexistent")
        assert is_stable is True
        assert final_score == 0.0

    def test_low_variance_is_stable(self) -> None:
        """Test that scores within threshold are marked stable."""
        tracker = StabilityTracker(variance_threshold=2.0)
        tracker.record_score("unit1", 85.0)
        tracker.record_score("unit1", 86.0)
        tracker.record_score("unit1", 86.5)

        is_stable, final_score = tracker.check_stability("unit1")
        assert is_stable is True
        assert final_score == 86.5  # Last score

    def test_high_variance_returns_median(self) -> None:
        """Test that high variance triggers unstable and returns median."""
        tracker = StabilityTracker(variance_threshold=2.0)
        tracker.record_score("unit1", 80.0)
        tracker.record_score("unit1", 85.0)
        tracker.record_score("unit1", 90.0)

        is_stable, final_score = tracker.check_stability("unit1")
        assert is_stable is False
        assert final_score == 85.0  # median of [80, 85, 90]

    def test_exactly_threshold_is_stable(self) -> None:
        """Test that variance exactly at threshold is considered stable."""
        tracker = StabilityTracker(variance_threshold=2.0)
        tracker.record_score("unit1", 80.0)
        tracker.record_score("unit1", 82.0)  # variance = 2.0

        is_stable, _ = tracker.check_stability("unit1")
        assert is_stable is True

    def test_unstable_warning(self) -> None:
        """Test that unstable units get Unstable_Score warning."""
        tracker = StabilityTracker(variance_threshold=2.0)
        tracker.record_score("unit1", 70.0)
        tracker.record_score("unit1", 85.0)

        warning = tracker.get_warning("unit1")
        assert warning == "Unstable_Score"

    def test_stable_no_warning(self) -> None:
        """Test that stable units have no warning."""
        tracker = StabilityTracker(variance_threshold=2.0)
        tracker.record_score("unit1", 85.0)
        tracker.record_score("unit1", 86.0)

        warning = tracker.get_warning("unit1")
        assert warning is None

    def test_multiple_units_independent(self) -> None:
        """Test that multiple units are tracked independently."""
        tracker = StabilityTracker(variance_threshold=2.0)

        tracker.record_score("unit1", 80.0)
        tracker.record_score("unit1", 90.0)  # unstable

        tracker.record_score("unit2", 85.0)
        tracker.record_score("unit2", 86.0)  # stable

        is_stable1, _ = tracker.check_stability("unit1")
        is_stable2, _ = tracker.check_stability("unit2")

        assert is_stable1 is False
        assert is_stable2 is True

    def test_median_with_even_count(self) -> None:
        """Test median calculation with even number of scores."""
        tracker = StabilityTracker(variance_threshold=0.1)
        tracker.record_score("unit1", 80.0)
        tracker.record_score("unit1", 82.0)

        _, final_score = tracker.check_stability("unit1")
        # median of [80, 82] = average = 81.0
        assert final_score == 81.0

    def test_clear_resets_all(self) -> None:
        """Test that clear removes all recorded scores."""
        tracker = StabilityTracker()
        tracker.record_score("unit1", 85.0)
        tracker.record_score("unit2", 90.0)

        tracker.clear()

        assert tracker.get_scores("unit1") == []
        assert tracker.get_scores("unit2") == []