"""
Client for the intervals.icu API.

Handles athlete profile retrieval, workout syncing, and recursive
workout block parsing (unfolding nested repeat groups into a flat list).
"""

import logging
from datetime import date, timedelta

import httpx

from app.config import settings
from app.models.athlete import AthleteProfile
from app.models.workout import BlockType, ParsedWorkout, WorkoutBlock

logger = logging.getLogger(__name__)

BASE_URL = "https://intervals.icu/api/v1"


class IntervalsClient:
    def __init__(
        self,
        api_key: str | None = None,
        athlete_id: str | None = None,
    ):
        self.api_key = api_key or settings.intervals_icu_api_key
        self.athlete_id = athlete_id or settings.intervals_icu_athlete_id
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            auth=("API_KEY", self.api_key),
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    # ── Athlete profile ──────────────────────────────────────────

    async def get_athlete_profile(self) -> AthleteProfile:
        resp = await self._client.get(f"/athlete/{self.athlete_id}")
        resp.raise_for_status()
        data = resp.json()

        return AthleteProfile(
            intervals_athlete_id=self.athlete_id,
            name=data.get("name", ""),
            weight_kg=data.get("weight", 75.0),
            ftp_watts=data.get("ftp", 250),
        )

    # ── Workouts ─────────────────────────────────────────────────

    async def get_events(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Get planned events (workouts) in a date range."""
        if date_from is None:
            date_from = date.today()
        if date_to is None:
            date_to = date_from + timedelta(days=7)

        resp = await self._client.get(
            f"/athlete/{self.athlete_id}/events",
            params={
                "oldest": date_from.isoformat(),
                "newest": date_to.isoformat(),
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_cycling_workouts(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Get only cycling workouts with workout definitions."""
        events = await self.get_events(date_from, date_to)
        return [
            e
            for e in events
            if e.get("category") == "WORKOUT"
            and e.get("type", "").lower() in ("ride", "cycling", "virtualride")
            and e.get("workout_doc")
        ]

    # ── Workout parsing ──────────────────────────────────────────

    def parse_workout(self, event: dict, ftp: int) -> ParsedWorkout:
        """Parse an intervals.icu event into a flat list of workout blocks."""
        workout_doc = event.get("workout_doc", {})
        name = event.get("name", "Unnamed workout")
        description = event.get("description", "")

        raw_steps = workout_doc.get("steps", [])
        blocks = self._flatten_steps(raw_steps, ftp)

        # Re-index blocks sequentially
        for i, block in enumerate(blocks):
            block.index = i

        return ParsedWorkout(
            name=name,
            description=description,
            blocks=blocks,
        )

    def _flatten_steps(
        self,
        steps: list[dict],
        ftp: int,
        repeat_idx: int | None = None,
    ) -> list[WorkoutBlock]:
        """Recursively flatten nested repeat groups into a flat block list."""
        blocks: list[WorkoutBlock] = []

        for step in steps:
            step_type = step.get("type", "").upper()

            if step_type == "REPEAT" or "steps" in step:
                # Nested repeat group: unfold N times
                repeat_count = step.get("count", step.get("repeat", 1))
                inner_steps = step.get("steps", [])
                for rep in range(repeat_count):
                    blocks.extend(
                        self._flatten_steps(inner_steps, ftp, repeat_idx=rep)
                    )
            else:
                block = self._parse_single_step(step, ftp, repeat_idx)
                if block:
                    blocks.append(block)

        return blocks

    def _parse_single_step(
        self,
        step: dict,
        ftp: int,
        repeat_idx: int | None = None,
    ) -> WorkoutBlock | None:
        """Parse a single non-repeat step into a WorkoutBlock."""
        duration = self._parse_duration(step)
        if duration <= 0:
            return None

        block_type = self._classify_step_type(step)
        power_watts, power_pct = self._resolve_power(step, ftp)

        return WorkoutBlock(
            index=0,  # will be re-indexed later
            block_type=block_type,
            duration_seconds=duration,
            power_watts=power_watts,
            power_percent_ftp=power_pct,
            cadence_target=step.get("cadence"),
            repeat_index=repeat_idx,
        )

    def _parse_duration(self, step: dict) -> int:
        """Extract duration in seconds from a step."""
        if "duration" in step:
            return int(step["duration"])
        if "seconds" in step:
            return int(step["seconds"])
        if "minutes" in step:
            return int(step["minutes"] * 60)
        # Distance-based steps: estimate from distance and power
        # (will be refined later with physics engine)
        if "distance" in step:
            # Rough estimate: 30 km/h = ~120m per second on flat
            return max(int(step["distance"] / 8.33), 60)
        return 0

    def _classify_step_type(self, step: dict) -> BlockType:
        """Map intervals.icu step type to our BlockType enum."""
        raw = step.get("type", "").upper()

        mapping = {
            "WARMUP": BlockType.WARMUP,
            "WARM_UP": BlockType.WARMUP,
            "COOLDOWN": BlockType.COOLDOWN,
            "COOL_DOWN": BlockType.COOLDOWN,
            "RECOVERY": BlockType.RECOVERY,
            "ACTIVE_RECOVERY": BlockType.RECOVERY,
            "REST": BlockType.REST,
            "INTERVAL": BlockType.INTERVAL,
            "WORK": BlockType.INTERVAL,
            "STEADY_STATE": BlockType.INTERVAL,
            "RAMP": BlockType.INTERVAL,
        }
        return mapping.get(raw, BlockType.INTERVAL)

    def _resolve_power(
        self, step: dict, ftp: int
    ) -> tuple[float, float | None]:
        """Resolve power to absolute watts. Returns (watts, percent_ftp_or_none)."""
        # Direct watts
        if "power" in step and isinstance(step["power"], (int, float)):
            watts = float(step["power"])
            return watts, watts / ftp * 100 if ftp > 0 else None

        # Percentage of FTP
        for key in ("power", "powerLow", "powerHigh"):
            val = step.get(key)
            if isinstance(val, dict):
                # intervals.icu format: {"value": 105, "units": "%ftp"}
                if val.get("units") in ("%ftp", "% ftp"):
                    pct = val["value"]
                    return ftp * pct / 100, pct

        # Range: use midpoint
        low = step.get("powerLow")
        high = step.get("powerHigh")
        if low is not None and high is not None:
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                mid = (low + high) / 2
                return mid, mid / ftp * 100 if ftp > 0 else None

        # Percentage as plain number (0-2 range = fraction of FTP)
        for key in ("power", "intensity"):
            val = step.get(key)
            if isinstance(val, (int, float)):
                if 0 < val <= 2.0:
                    # Likely a fraction of FTP
                    pct = val * 100
                    return ftp * val, pct
                elif val > 2:
                    # Likely absolute watts
                    return float(val), val / ftp * 100 if ftp > 0 else None

        # RPE fallback: conservative estimate
        rpe = step.get("rpe")
        if rpe is not None:
            return self._rpe_to_watts(rpe, ftp), None

        # Default: endurance zone (60% FTP)
        logger.warning("No power target found in step, defaulting to 60%% FTP")
        return ftp * 0.60, 60.0

    @staticmethod
    def _rpe_to_watts(rpe: float, ftp: int) -> float:
        """Conservative RPE → watts mapping based on standard zones."""
        rpe_to_pct = {
            1: 0.45, 2: 0.50, 3: 0.55, 4: 0.60, 5: 0.70,
            6: 0.80, 7: 0.90, 8: 0.95, 9: 1.05, 10: 1.15,
        }
        pct = rpe_to_pct.get(int(min(max(rpe, 1), 10)), 0.60)
        return ftp * pct
