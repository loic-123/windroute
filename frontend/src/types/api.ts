export interface AthleteProfile {
  id: string;
  intervals_athlete_id: string;
  name: string;
  weight_kg: number;
  ftp_watts: number;
  cda: number;
  bike_weight_kg: number;
  crr: number;
  home_lat: number | null;
  home_lon: number | null;
  default_position: string;
  preferences: Record<string, unknown>;
}

export interface WorkoutBlock {
  index: number;
  block_type: string;
  duration_seconds: number;
  power_watts: number;
  power_percent_ftp: number | null;
  cadence_target: number | null;
  repeat_index: number | null;
}

export interface Workout {
  id: string;
  name: string;
  description: string;
  planned_date: string;
  sport_type: string;
  duration_seconds: number | null;
  tss_planned: number | null;
  block_count: number;
  blocks: WorkoutBlock[];
}

export interface WeatherSnapshot {
  timestamp: string;
  wind_speed_kmh: number;
  wind_direction_deg: number;
  wind_direction_label: string;
  temperature_c: number;
  cloudcover_percent: number;
  precipitation_mm: number;
  surface_pressure_hpa: number;
}

export interface WeatherForecast {
  snapshots: WeatherSnapshot[];
  wind_shift_warning: string | null;
}

export interface Climb {
  id: string;
  length_km: number;
  avg_grade_percent: number;
  max_grade_percent: number;
  elevation_gain_m: number;
  estimated_duration_s: number;
  quality_score: number;
  road_type: string;
}

export interface RouteData {
  id: string;
  variant: string;
  name: string;
  status: string;
  total_distance_km: number | null;
  total_elevation_m: number | null;
  estimated_duration_s: number | null;
  warmup_distance_km: number | null;
  cooldown_distance_km: number | null;
  wind_score: number | null;
  climb_score: number | null;
  sunshine_score: number | null;
  heatmap_score: number | null;
  overall_score: number | null;
  geojson: GeoJSON.FeatureCollection | null;
  climbs: Climb[];
  warnings: string[];
  weather_snapshot: Record<string, unknown> | null;
}

export interface GenerationJob {
  job_id: string;
  status: string;
  progress_percent: number;
  progress_message: string | null;
  route_ids: string[];
  error_message: string | null;
}

export interface GenerateRequest {
  athlete_id?: string;
  workout_id?: string;
  manual_workout?: Record<string, unknown>;
  start_lat: number;
  start_lon: number;
  departure_time?: string;
  options?: Record<string, unknown>;
}
