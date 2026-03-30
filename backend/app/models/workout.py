from dataclasses import dataclass
from enum import Enum


class BlockType(str, Enum):
    WARMUP = "warmup"
    INTERVAL = "interval"
    RECOVERY = "recovery"
    COOLDOWN = "cooldown"
    REST = "rest"


@dataclass
class WorkoutBlock:
    """A single flat workout block after recursive unfolding."""

    index: int
    block_type: BlockType
    duration_seconds: int
    power_watts: float
    power_percent_ftp: float | None = None
    cadence_target: int | None = None
    repeat_index: int | None = None  # which repetition this is (0-based)

    @property
    def is_effort(self) -> bool:
        return self.block_type == BlockType.INTERVAL


@dataclass
class ParsedWorkout:
    """Fully parsed workout with flat block list."""

    name: str
    description: str = ""
    total_duration_seconds: int = 0
    blocks: list[WorkoutBlock] | None = None

    def __post_init__(self):
        if self.blocks is None:
            self.blocks = []
        self.total_duration_seconds = sum(b.duration_seconds for b in self.blocks)

    @property
    def interval_blocks(self) -> list[WorkoutBlock]:
        return [b for b in self.blocks if b.is_effort]

    @property
    def interval_count(self) -> int:
        return len(self.interval_blocks)

    @property
    def has_intervals(self) -> bool:
        return self.interval_count > 0
