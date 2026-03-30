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

        # Weight is in icu_weight, not weight
        weight = data.get("icu_weight") or data.get("weight") or 75.0

        # FTP is in sportSettings[0].ftp for cycling
        ftp = 250
        sport_settings = data.get("sportSettings", [])
        for ss in sport_settings:
            types = ss.get("types", [])
            if any(t in types for t in ["Ride", "VirtualRide", "Cycling"]):
                ftp = ss.get("ftp", 250) or 250
                break

        name = data.get("name") or data.get("firstname", "")

        return AthleteProfile(
            intervals_athlete_id=self.athlete_id,
            name=name,
            weight_kg=float(weight),
            ftp_watts=int(ftp),
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
            and e.get("type", "").lower() in (
                "ride", "cycling", "virtualride", "mountainbikeride", "gravelride", "trackride"
            )
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
            # Repeat block: has "reps" or "steps" with nested children
            if "steps" in step:
                repeat_count = step.get("reps", step.get("count", step.get("repeat", 1)))
                inner_steps = step["steps"]
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

        # Parse cadence from dict format {"units": "rpm", "value": 85}
        cadence = step.get("cadence")
        cadence_target = None
        if isinstance(cadence, dict):
            cadence_target = cadence.get("value")
        elif isinstance(cadence, (int, float)):
            cadence_target = int(cadence)

        return WorkoutBlock(
            index=0,  # will be re-indexed later
            block_type=block_type,
            duration_seconds=duration,
            power_watts=power_watts,
            power_percent_ftp=power_pct,
            cadence_target=cadence_target,
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
        if "distance" in step:
            return max(int(step["distance"] / 8.33), 60)
        return 0

    def _classify_step_type(self, step: dict) -> BlockType:
        """Map intervals.icu step to our BlockType.

        Intervals.icu uses boolean flags (warmup, cooldown) on steps
        rather than a type field. Text hints also help classify.
        """
        # Boolean flags (intervals.icu native format)
        if step.get("warmup"):
            return BlockType.WARMUP
        if step.get("cooldown"):
            return BlockType.COOLDOWN

        # Check type field if present
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
        if raw in mapping:
            return mapping[raw]

        # Heuristic from text
        text = (step.get("text") or "").lower()
        if "recovery" in text or "recup" in text:
            return BlockType.RECOVERY
        if "warm" in text:
            return BlockType.WARMUP
        if "cool" in text:
            return BlockType.COOLDOWN

        # Heuristic from power level
        power = step.get("power")
        if isinstance(power, dict):
            pct = power.get("value") or power.get("end") or 0
            if power.get("units") in ("%ftp", "% ftp") and pct <= 55:
                return BlockType.RECOVERY

        return BlockType.INTERVAL

    def _resolve_power(
        self, step: dict, ftp: int
    ) -> tuple[float, float | None]:
        """Resolve power to absolute watts. Returns (watts, percent_ftp_or_none).

        Handles intervals.icu formats:
          - {"units": "%ftp", "value": 65}         fixed target
          - {"units": "%ftp", "start": 45, "end": 75}  ramp/range
          - {"units": "power_zone", "value": 2}    zone reference
        """
        power = step.get("power")

        if power is None:
            # Running workout or no power target — default to endurance
            pace = step.get("pace")
            if pace:
                logger.debug("Step uses pace, not power — defaulting to 60%% FTP")
            return ftp * 0.60, 60.0

        # Direct watts (unlikely but handle)
        if isinstance(power, (int, float)):
            return float(power), power / ftp * 100 if ftp > 0 else None

        # Dict format
        if isinstance(power, dict):
            units = power.get("units", "")

            if units in ("%ftp", "% ftp", "%FTP"):
                # Fixed value or ramp (start/end)
                if "value" in power:
                    pct = float(power["value"])
                elif "start" in power and "end" in power:
                    # Use midpoint for ramps
                    pct = (float(power["start"]) + float(power["end"])) / 2
                elif "start" in power:
                    pct = float(power["start"])
                elif "end" in power:
                    pct = float(power["end"])
                else:
                    pct = 60.0
                return ftp * pct / 100, pct

            elif units == "power_zone":
                # Map zone number to approximate %FTP
                zone_pct = {1: 50, 2: 60, 3: 75, 4: 90, 5: 105, 6: 120, 7: 140}
                zone = int(power.get("value", 2))
                pct = zone_pct.get(zone, 60)
                return ftp * pct / 100, float(pct)

            elif units in ("watts", "W", "w"):
                watts = float(power.get("value", power.get("start", 0)))
                return watts, watts / ftp * 100 if ftp > 0 else None

        # Fallback
        logger.warning("Unrecognized power format: %s — defaulting to 60%% FTP", power)
        return ftp * 0.60, 60.0
