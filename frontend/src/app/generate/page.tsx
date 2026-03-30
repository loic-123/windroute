"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { WindCompass } from "@/components/weather/wind-compass";
import { WorkoutBlocks } from "@/components/workout/workout-blocks";
import { Loader2, Play, CheckCircle, XCircle, LocateFixed } from "lucide-react";
import type { GenerateRequest } from "@/types/api";

export default function GeneratePageWrapper() {
  return (
    <Suspense fallback={<p className="text-gray-400">Chargement...</p>}>
      <GeneratePage />
    </Suspense>
  );
}

function GeneratePage() {
  const searchParams = useSearchParams();
  const workoutId = searchParams.get("workout_id");

  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: api.getProfile,
  });

  const { data: workout } = useQuery({
    queryKey: ["workout", workoutId],
    queryFn: () => (workoutId ? api.getWorkout(workoutId) : null),
    enabled: !!workoutId,
  });

  const [lat, setLat] = useState(48.1173);
  const [lon, setLon] = useState(-1.6778);
  const [climbMode, setClimbMode] = useState("auto");
  const [maxRadius, setMaxRadius] = useState(40);
  const [jobId, setJobId] = useState<string | null>(null);

  const geolocate = () => {
    navigator.geolocation?.getCurrentPosition(
      (pos) => {
        setLat(+pos.coords.latitude.toFixed(6));
        setLon(+pos.coords.longitude.toFixed(6));
      },
      () => {},
      { enableHighAccuracy: true }
    );
  };

  useEffect(() => {
    if (profile?.home_lat && profile?.home_lon) {
      setLat(profile.home_lat);
      setLon(profile.home_lon);
    }
  }, [profile]);

  const { data: weather } = useQuery({
    queryKey: ["weather", lat, lon],
    queryFn: () => api.getWeather(lat, lon),
    enabled: !!lat && !!lon,
  });

  const generateMutation = useMutation({
    mutationFn: (req: GenerateRequest) => api.generateRoutes(req),
    onSuccess: (data) => setJobId(data.job_id),
  });

  const { data: jobStatus } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => (jobId ? api.getJobStatus(jobId) : null),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2000;
    },
  });

  const handleGenerate = () => {
    const request: GenerateRequest = {
      workout_id: workoutId || undefined,
      start_lat: lat,
      start_lon: lon,
      options: {
        climb_mode: climbMode,
        max_radius_km: maxRadius,
      },
    };
    generateMutation.mutate(request);
  };

  const current = weather?.snapshots?.[0];
  const isGenerating = jobStatus?.status === "running" || jobStatus?.status === "queued";
  const isDone = jobStatus?.status === "completed";
  const isFailed = jobStatus?.status === "failed";

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold">Generer une route</h1>

      {/* Workout preview */}
      {workout && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="font-medium mb-2">{workout.name}</h2>
          <WorkoutBlocks blocks={workout.blocks} />
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Parameters */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-medium text-gray-300">Parametres</h2>
            <button
              type="button"
              onClick={geolocate}
              className="flex items-center gap-1 px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs font-medium"
            >
              <LocateFixed size={14} />
              Ma position
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Latitude</label>
              <input
                type="number"
                step="0.0001"
                value={lat}
                onChange={(e) => setLat(+e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Longitude</label>
              <input
                type="number"
                step="0.0001"
                value={lon}
                onChange={(e) => setLon(+e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Mode montees</label>
            <select
              value={climbMode}
              onChange={(e) => setClimbMode(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
            >
              <option value="auto">Auto</option>
              <option value="repeat">Repeat (meme montee N fois)</option>
              <option value="loop">Loop (N montees differentes)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Rayon max: {maxRadius} km
            </label>
            <input
              type="range"
              min={5}
              max={60}
              value={maxRadius}
              onChange={(e) => setMaxRadius(+e.target.value)}
              className="w-full"
            />
          </div>
        </div>

        {/* Weather preview */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 flex flex-col items-center justify-center">
          {current ? (
            <>
              <WindCompass
                direction_deg={current.wind_direction_deg}
                speed_kmh={current.wind_speed_kmh}
                label={current.wind_direction_label}
              />
              <div className="mt-3 text-center text-sm text-gray-400">
                <p>{current.temperature_c.toFixed(1)}°C | Nuages: {current.cloudcover_percent}%</p>
                {current.precipitation_mm > 0 && (
                  <p className="text-yellow-400">Pluie: {current.precipitation_mm} mm</p>
                )}
              </div>
              {weather?.wind_shift_warning && (
                <p className="text-yellow-400 text-xs mt-2">{weather.wind_shift_warning}</p>
              )}
            </>
          ) : (
            <p className="text-gray-500">Chargement meteo...</p>
          )}
        </div>
      </div>

      {/* Generate button */}
      {!isGenerating && !isDone && (
        <button
          onClick={handleGenerate}
          disabled={generateMutation.isPending}
          className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-700 rounded-lg font-medium text-lg disabled:opacity-50"
        >
          <Play size={20} />
          Lancer la generation
        </button>
      )}

      {/* Progress */}
      {isGenerating && jobStatus && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
          <div className="flex items-center gap-3">
            <Loader2 size={20} className="animate-spin text-blue-400" />
            <span className="font-medium">Generation en cours...</span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${jobStatus.progress_percent}%` }}
            />
          </div>
          <p className="text-sm text-gray-400">{jobStatus.progress_message}</p>
        </div>
      )}

      {/* Success */}
      {isDone && jobStatus && (
        <div className="bg-gray-900 border border-green-800 rounded-lg p-5 space-y-3">
          <div className="flex items-center gap-3">
            <CheckCircle size={20} className="text-green-400" />
            <span className="font-medium text-green-400">
              {jobStatus.route_ids.length} routes generees
            </span>
          </div>
          <div className="flex gap-3">
            {jobStatus.route_ids.map((id, i) => (
              <a
                key={id}
                href={`/routes/${id}`}
                className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded text-sm font-medium"
              >
                Variante {["A", "B", "C"][i]}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {isFailed && jobStatus && (
        <div className="bg-gray-900 border border-red-800 rounded-lg p-5">
          <div className="flex items-center gap-3">
            <XCircle size={20} className="text-red-400" />
            <span className="text-red-400">{jobStatus.error_message}</span>
          </div>
        </div>
      )}
    </div>
  );
}
