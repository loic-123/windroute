from dataclasses import dataclass, field


@dataclass
class AthleteProfile:
    id: str = ""
    intervals_athlete_id: str = ""
    name: str = ""
    weight_kg: float = 75.0
    ftp_watts: int = 250
    cda: float = 0.36
    bike_weight_kg: float = 8.0
    crr: float = 0.004
    home_lat: float | None = None
    home_lon: float | None = None
    default_position: str = "hoods"
    preferences: dict = field(default_factory=dict)

    # CdA lookup by position
    CDA_BY_POSITION: dict[str, float] = field(
        default_factory=lambda: {
            "tops": 0.40,
            "hoods": 0.36,
            "standing": 0.44,
            "drops": 0.28,
            "aero": 0.24,
        },
        repr=False,
    )

    def get_cda(self, position: str | None = None) -> float:
        pos = position or self.default_position
        return self.CDA_BY_POSITION.get(pos, self.cda)
