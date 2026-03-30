"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { RouteMap } from "@/components/map/route-map";
import { RouteScores } from "@/components/route/route-scores";
import { RouteElevation } from "@/components/route/route-elevation";
import {
  formatDistance,
  formatDuration,
  formatElevation,
} from "@/lib/utils";
import { Download, Star, AlertTriangle } from "lucide-react";
import { use } from "react";

export default function RouteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: route, isLoading } = useQuery({
    queryKey: ["route", id],
    queryFn: () => api.getRoute(id),
  });

  const selectMutation = useMutation({
    mutationFn: () => api.selectRoute(id),
  });

  if (isLoading) return <p className="text-gray-400">Chargement...</p>;
  if (!route) return <p className="text-red-400">Route non trouvee</p>;

  const center: [number, number] = route.geojson?.features?.[0]?.geometry?.type === "LineString"
    ? (() => {
        const coords = (route.geojson!.features[0].geometry as GeoJSON.LineString).coordinates;
        const mid = coords[Math.floor(coords.length / 2)];
        return [mid[1], mid[0]] as [number, number];
      })()
    : [48.1173, -1.6778];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{route.name}</h1>
          <div className="flex items-center gap-4 text-sm text-gray-400 mt-1">
            <span>{formatDistance(route.total_distance_km || 0)}</span>
            <span>D+ {formatElevation(route.total_elevation_m || 0)}</span>
            <span>
              {route.estimated_duration_s
                ? formatDuration(route.estimated_duration_s)
                : "—"}
            </span>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => selectMutation.mutate()}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded text-sm font-medium"
          >
            <Star size={16} />
            Selectionner
          </button>
          <a
            href={api.getGpxUrl(id)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium"
          >
            <Download size={16} />
            GPX
          </a>
        </div>
      </div>

      {/* Warnings */}
      {route.warnings.length > 0 && (
        <div className="bg-yellow-900/30 border border-yellow-800 rounded-lg p-4 space-y-1">
          {route.warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-2 text-yellow-400 text-sm">
              <AlertTriangle size={14} />
              {w}
            </div>
          ))}
        </div>
      )}

      {/* Map */}
      <RouteMap geojson={route.geojson} center={center} />

      {/* Elevation profile */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-400 mb-3">
          Profil d&apos;elevation
        </h2>
        <RouteElevation
          coords={
            route.geojson?.features
              ?.filter((f) => f.geometry.type === "LineString")
              .flatMap((f) =>
                (f.geometry as GeoJSON.LineString).coordinates.map(
                  (c) => [c[1], c[0], c[2] || 0] as [number, number, number]
                )
              ) || null
          }
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Scores */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Scores</h2>
          <RouteScores
            wind_score={route.wind_score}
            climb_score={route.climb_score}
            sunshine_score={route.sunshine_score}
            heatmap_score={route.heatmap_score}
            overall_score={route.overall_score}
          />
        </div>

        {/* Climbs */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Montees</h2>
          {route.climbs.length > 0 ? (
            <div className="space-y-3">
              {route.climbs.map((climb) => (
                <div
                  key={climb.id}
                  className="bg-gray-800 rounded p-3 space-y-1"
                >
                  <div className="flex justify-between">
                    <span className="font-medium text-sm">
                      {formatDistance(climb.length_km)}
                    </span>
                    <span className="text-sm text-orange-400">
                      {climb.avg_grade_percent.toFixed(1)}% moy
                    </span>
                  </div>
                  <div className="text-xs text-gray-400 flex gap-3">
                    <span>D+ {formatElevation(climb.elevation_gain_m)}</span>
                    <span>Max {climb.max_grade_percent.toFixed(1)}%</span>
                    <span>
                      {formatDuration(Math.round(climb.estimated_duration_s))}
                    </span>
                    <span>{climb.road_type}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">Pas de montees (seance endurance)</p>
          )}
        </div>
      </div>

      {/* Weather at generation */}
      {route.weather_snapshot && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-2">
            Meteo lors de la generation
          </h2>
          <div className="flex gap-4 text-sm text-gray-300">
            <span>
              Vent: {(route.weather_snapshot as Record<string, number>).wind_speed_kmh?.toFixed(0)} km/h{" "}
              {(route.weather_snapshot as Record<string, string>).wind_direction_label}
            </span>
            <span>
              Temp: {(route.weather_snapshot as Record<string, number>).temperature_c?.toFixed(1)}°C
            </span>
            <span>
              Nuages: {(route.weather_snapshot as Record<string, number>).cloudcover_percent}%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
