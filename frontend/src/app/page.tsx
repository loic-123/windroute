"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Wind, Thermometer, Cloud, MapPin } from "lucide-react";

export default function Dashboard() {
  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: api.getProfile,
  });

  const { data: weather } = useQuery({
    queryKey: ["weather", profile?.home_lat, profile?.home_lon],
    queryFn: () =>
      profile?.home_lat && profile?.home_lon
        ? api.getWeather(profile.home_lat, profile.home_lon)
        : null,
    enabled: !!profile?.home_lat && !!profile?.home_lon,
  });

  const { data: routes } = useQuery({
    queryKey: ["routes"],
    queryFn: () => api.getRoutes(5),
  });

  const current = weather?.snapshots?.[0];

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Profile card */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Athlete</h2>
          {profile ? (
            <div className="space-y-2">
              <p className="text-lg font-semibold">{profile.name || "Non configure"}</p>
              <p className="text-sm text-gray-400">
                FTP: {profile.ftp_watts}W | Poids: {profile.weight_kg} kg
              </p>
              {profile.home_lat && (
                <p className="text-sm text-gray-500 flex items-center gap-1">
                  <MapPin size={14} />
                  {profile.home_lat.toFixed(4)}, {profile.home_lon?.toFixed(4)}
                </p>
              )}
            </div>
          ) : (
            <p className="text-gray-500">Chargement...</p>
          )}
        </div>

        {/* Weather card */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Meteo</h2>
          {current ? (
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <Wind size={20} className="text-blue-400" />
                <span className="text-lg font-semibold">
                  {current.wind_speed_kmh.toFixed(0)} km/h {current.wind_direction_label}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Thermometer size={20} className="text-orange-400" />
                <span>{current.temperature_c.toFixed(1)}°C</span>
              </div>
              <div className="flex items-center gap-3">
                <Cloud size={20} className="text-gray-400" />
                <span>{current.cloudcover_percent}% couverture nuageuse</span>
              </div>
              {weather?.wind_shift_warning && (
                <p className="text-yellow-400 text-sm mt-2">
                  {weather.wind_shift_warning}
                </p>
              )}
            </div>
          ) : (
            <p className="text-gray-500">
              {profile?.home_lat ? "Chargement..." : "Configurez votre localisation"}
            </p>
          )}
        </div>

        {/* Recent routes card */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Routes recentes</h2>
          {routes && routes.length > 0 ? (
            <div className="space-y-2">
              {routes.slice(0, 3).map((r) => (
                <a
                  key={r.id}
                  href={`/routes/${r.id}`}
                  className="block p-2 rounded hover:bg-gray-800 transition-colors"
                >
                  <p className="text-sm font-medium truncate">{r.name}</p>
                  <p className="text-xs text-gray-500">
                    {r.total_distance_km?.toFixed(1)} km | D+{" "}
                    {r.total_elevation_m?.toFixed(0)} m
                  </p>
                </a>
              ))}
            </div>
          ) : (
            <p className="text-gray-500">Aucune route generee</p>
          )}
        </div>
      </div>
    </div>
  );
}
