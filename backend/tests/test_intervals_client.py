"""Tests for the intervals.icu workout parser."""

import json
from pathlib import Path

from app.clients.intervals_client import IntervalsClient
from app.models.workout import BlockType


def load_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text())


class TestWorkoutParser:
    def setup_method(self):
        self.client = IntervalsClient(api_key="test", athlete_id="test")

    def test_parse_5x5min_workout(self):
        event = load_fixture("sample_workout.json")
        ftp = 280

        workout = self.client.parse_workout(event, ftp)

        assert workout.name == "5x5min @ 105% FTP"
        assert workout.has_intervals

        # Should have: 1 warmup + 5*(interval+recovery) + 1 cooldown = 12 blocks
        assert len(workout.blocks) == 12

        # First block is warmup
        assert workout.blocks[0].block_type == BlockType.WARMUP
        assert workout.blocks[0].duration_seconds == 900
        assert abs(workout.blocks[0].power_watts - ftp * 0.55) < 1

        # Second block is first interval
        assert workout.blocks[1].block_type == BlockType.INTERVAL
        assert workout.blocks[1].duration_seconds == 300
        assert abs(workout.blocks[1].power_watts - ftp * 1.05) < 1

        # Third block is first recovery
        assert workout.blocks[2].block_type == BlockType.RECOVERY
        assert workout.blocks[2].duration_seconds == 180

        # Last block is cooldown
        assert workout.blocks[-1].block_type == BlockType.COOLDOWN
        assert workout.blocks[-1].duration_seconds == 600

    def test_interval_count(self):
        event = load_fixture("sample_workout.json")
        workout = self.client.parse_workout(event, 280)

        assert workout.interval_count == 5

    def test_blocks_are_sequentially_indexed(self):
        event = load_fixture("sample_workout.json")
        workout = self.client.parse_workout(event, 280)

        for i, block in enumerate(workout.blocks):
            assert block.index == i

    def test_total_duration(self):
        event = load_fixture("sample_workout.json")
        workout = self.client.parse_workout(event, 280)

        expected = 900 + 5 * (300 + 180) + 600  # = 3900s = 65min
        assert workout.total_duration_seconds == expected
