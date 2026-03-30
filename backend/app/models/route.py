from dataclasses import dataclass, field


@dataclass
class ClimbCandidate:
    """A detected climb segment from OSM data."""

    start_node: int
    end_node: int
    length_m: float
    avg_grade_percent: float
    max_grade_percent: float
    elevation_gain_m: float
    grade_stddev: float
    road_type: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    estimated_duration_s: float = 0.0
    quality_score: float = 0.0
    heatmap_score: float = 0.5


@dataclass
class RouteSegment:
    """A segment of the route tied to a workout block."""

    block_index: int
    block_type: str
    nodes: list[int] = field(default_factory=list)
    coords: list[tuple[float, float, float]] = field(default_factory=list)
    distance_m: float = 0.0
    duration_s: float = 0.0
    power_target: float = 0.0
    avg_speed_ms: float = 0.0
    avg_grade_percent: float = 0.0
    climb: ClimbCandidate | None = None


@dataclass
class Route:
    """A complete generated route with scoring."""

    variant: str  # A, B, or C
    nodes: list[int] = field(default_factory=list)
    coords: list[tuple[float, float, float]] = field(default_factory=list)
    segments: list[RouteSegment] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_elevation_m: float = 0.0
    estimated_duration_s: int = 0

    # Actual durations (may differ from initial due to elasticity)
    warmup_duration_initial_s: int = 0
    warmup_duration_actual_s: int = 0
    cooldown_duration_initial_s: int = 0
    cooldown_duration_actual_s: int = 0
    warmup_distance_km: float = 0.0
    cooldown_distance_km: float = 0.0

    # Scores (0.0 to 1.0)
    wind_score: float = 0.0
    climb_score: float = 0.0
    sunshine_score: float = 0.0
    heatmap_score: float = 0.5
    overall_score: float = 0.0

    # Metadata
    climbs: list[ClimbCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    geojson: dict | None = None
    gpx_data: str = ""
