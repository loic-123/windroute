"""Tests for the timing engine."""

from app.engine.timing import compute_block_distances, compute_elastic_max
from app.models.workout import BlockType, WorkoutBlock


class TestElasticMax:
    def test_short_duration(self):
        """30min warmup → max = 30 * 1.40 = 42 min."""
        result = compute_elastic_max(1800)
        assert result == 2520

    def test_long_duration(self):
        """1h warmup → max = 60 * 1.20 = 72 min."""
        result = compute_elastic_max(3600)
        assert result == 4320

    def test_boundary(self):
        """Just under 1h: 59min → 40% elastic."""
        result = compute_elastic_max(3540)
        expected = int(3540 * 1.40)
        assert result == expected


class TestBlockDistances:
    def test_basic(self):
        blocks = [
            WorkoutBlock(index=0, block_type=BlockType.WARMUP, duration_seconds=600, power_watts=150),
            WorkoutBlock(index=1, block_type=BlockType.INTERVAL, duration_seconds=300, power_watts=280),
        ]
        speeds = [7.0, 5.0]  # m/s

        result = compute_block_distances(blocks, speeds)
        assert len(result) == 2
        assert result[0]["start_distance_m"] == 0.0
        assert result[0]["distance_m"] == 4200.0  # 7 * 600
        assert result[1]["start_distance_m"] == 4200.0
        assert result[1]["distance_m"] == 1500.0  # 5 * 300

    def test_mismatched_lengths_raises(self):
        blocks = [
            WorkoutBlock(index=0, block_type=BlockType.WARMUP, duration_seconds=600, power_watts=150),
        ]
        speeds = [7.0, 5.0]
        try:
            compute_block_distances(blocks, speeds)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
