-- WindRoute — Initial schema
-- 5 tables: athletes, workouts, generated_routes, route_climbs, generation_jobs

-- ============================================================
-- athletes: profil athlète
-- ============================================================
CREATE TABLE athletes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intervals_athlete_id TEXT UNIQUE,
  intervals_api_key TEXT,
  name TEXT,
  weight_kg NUMERIC(5,1) NOT NULL DEFAULT 75.0,
  ftp_watts INTEGER NOT NULL DEFAULT 250,
  cda NUMERIC(4,3) NOT NULL DEFAULT 0.360,
  bike_weight_kg NUMERIC(4,1) NOT NULL DEFAULT 8.0,
  crr NUMERIC(5,4) NOT NULL DEFAULT 0.0040,
  home_lat NUMERIC(9,6),
  home_lon NUMERIC(9,6),
  default_position TEXT DEFAULT 'hoods',
  strava_access_token TEXT,
  preferences JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- workouts: séances synchronisées depuis intervals.icu
-- ============================================================
CREATE TABLE workouts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  intervals_event_id TEXT,
  name TEXT NOT NULL,
  description TEXT,
  planned_date DATE NOT NULL,
  sport_type TEXT DEFAULT 'cycling',
  duration_seconds INTEGER,
  tss_planned NUMERIC(5,1),
  workout_definition JSONB NOT NULL,
  parsed_blocks JSONB NOT NULL,
  block_count INTEGER GENERATED ALWAYS AS (jsonb_array_length(parsed_blocks)) STORED,
  synced_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_workouts_athlete_date ON workouts(athlete_id, planned_date);
CREATE INDEX idx_workouts_planned_date ON workouts(planned_date);

-- ============================================================
-- generated_routes: routes générées par le moteur
-- ============================================================
CREATE TABLE generated_routes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  workout_id UUID REFERENCES workouts(id) ON DELETE SET NULL,
  variant TEXT NOT NULL CHECK (variant IN ('A', 'B', 'C')),
  name TEXT NOT NULL,
  status TEXT DEFAULT 'pending'
    CHECK (status IN ('pending', 'generating', 'completed', 'failed')),

  -- Données géographiques
  gpx_data TEXT,
  geojson JSONB,
  coords JSONB,
  start_lat NUMERIC(9,6),
  start_lon NUMERIC(9,6),

  -- Métriques
  total_distance_km NUMERIC(6,2),
  total_elevation_m NUMERIC(7,1),
  warmup_distance_km NUMERIC(5,2),
  warmup_duration_actual_s INTEGER,
  warmup_duration_initial_s INTEGER,
  cooldown_distance_km NUMERIC(5,2),
  cooldown_duration_actual_s INTEGER,
  cooldown_duration_initial_s INTEGER,
  estimated_duration_s INTEGER,

  -- Scores (0.0 à 1.0)
  wind_score NUMERIC(4,3),
  climb_score NUMERIC(4,3),
  sunshine_score NUMERIC(4,3),
  heatmap_score NUMERIC(4,3),
  overall_score NUMERIC(4,3),

  -- Contexte météo
  weather_snapshot JSONB,
  generation_params JSONB,
  warnings JSONB DEFAULT '[]',
  summary_json JSONB,
  selected BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_routes_athlete ON generated_routes(athlete_id);
CREATE INDEX idx_routes_workout ON generated_routes(workout_id);
CREATE INDEX idx_routes_status ON generated_routes(status);

-- ============================================================
-- route_climbs: montées associées à une route
-- ============================================================
CREATE TABLE route_climbs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  route_id UUID NOT NULL REFERENCES generated_routes(id) ON DELETE CASCADE,
  climb_index INTEGER NOT NULL,
  name TEXT,
  length_m NUMERIC(8,1),
  avg_grade_percent NUMERIC(4,1),
  max_grade_percent NUMERIC(4,1),
  elevation_gain_m NUMERIC(6,1),
  grade_stddev NUMERIC(4,2),
  road_type TEXT,
  start_lat NUMERIC(9,6),
  start_lon NUMERIC(9,6),
  end_lat NUMERIC(9,6),
  end_lon NUMERIC(9,6),
  matched_interval_index INTEGER,
  estimated_duration_s INTEGER,
  climb_mode TEXT CHECK (climb_mode IN ('repeat', 'loop')),
  quality_score NUMERIC(4,3)
);

CREATE INDEX idx_route_climbs_route ON route_climbs(route_id);

-- ============================================================
-- generation_jobs: suivi asynchrone des générations
-- ============================================================
CREATE TABLE generation_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  workout_id UUID REFERENCES workouts(id),
  status TEXT DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
  progress_percent INTEGER DEFAULT 0,
  progress_message TEXT,
  route_ids UUID[] DEFAULT '{}',
  error_message TEXT,
  params JSONB NOT NULL,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_jobs_athlete ON generation_jobs(athlete_id);
CREATE INDEX idx_jobs_status ON generation_jobs(status);
