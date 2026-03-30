"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Save, RefreshCw } from "lucide-react";

export default function ProfilePage() {
  const queryClient = useQueryClient();
  const { data: profile, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn: api.getProfile,
  });

  const [form, setForm] = useState({
    name: "",
    weight_kg: 75,
    ftp_watts: 250,
    cda: 0.36,
    bike_weight_kg: 8.0,
    crr: 0.004,
    home_lat: 48.1173,
    home_lon: -1.6778,
    default_position: "hoods",
    intervals_api_key: "",
    intervals_athlete_id: "",
  });

  const [initialized, setInitialized] = useState(false);

  if (profile && !initialized) {
    setForm({
      name: profile.name || "",
      weight_kg: profile.weight_kg,
      ftp_watts: profile.ftp_watts,
      cda: profile.cda,
      bike_weight_kg: profile.bike_weight_kg,
      crr: profile.crr,
      home_lat: profile.home_lat || 48.1173,
      home_lon: profile.home_lon || -1.6778,
      default_position: profile.default_position,
      intervals_api_key: "",
      intervals_athlete_id: profile.intervals_athlete_id || "",
    });
    setInitialized(true);
  }

  const updateMutation = useMutation({
    mutationFn: (data: typeof form) => api.updateProfile(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["profile"] }),
  });

  const syncMutation = useMutation({
    mutationFn: () =>
      api.syncProfile(form.intervals_api_key, form.intervals_athlete_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      setInitialized(false);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateMutation.mutate(form);
  };

  if (isLoading) return <p className="text-gray-400">Chargement...</p>;

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Profil Athlete</h1>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Identity */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h2 className="font-medium text-gray-300">Identite</h2>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Nom</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
            />
          </div>
        </section>

        {/* Physical */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h2 className="font-medium text-gray-300">Parametres physiques</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Poids (kg)</label>
              <input
                type="number"
                step="0.1"
                value={form.weight_kg}
                onChange={(e) => setForm({ ...form, weight_kg: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">FTP (W)</label>
              <input
                type="number"
                value={form.ftp_watts}
                onChange={(e) => setForm({ ...form, ftp_watts: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">CdA (m²)</label>
              <input
                type="number"
                step="0.01"
                value={form.cda}
                onChange={(e) => setForm({ ...form, cda: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Poids velo (kg)</label>
              <input
                type="number"
                step="0.1"
                value={form.bike_weight_kg}
                onChange={(e) => setForm({ ...form, bike_weight_kg: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Crr</label>
              <input
                type="number"
                step="0.001"
                value={form.crr}
                onChange={(e) => setForm({ ...form, crr: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Position</label>
              <select
                value={form.default_position}
                onChange={(e) => setForm({ ...form, default_position: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              >
                <option value="tops">Mains dessus (0.40)</option>
                <option value="hoods">Cocottes (0.36)</option>
                <option value="drops">Bas du guidon (0.28)</option>
                <option value="standing">Danseuse (0.44)</option>
                <option value="aero">CLM/Tri (0.24)</option>
              </select>
            </div>
          </div>
        </section>

        {/* Location */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h2 className="font-medium text-gray-300">Localisation</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Latitude</label>
              <input
                type="number"
                step="0.0001"
                value={form.home_lat}
                onChange={(e) => setForm({ ...form, home_lat: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Longitude</label>
              <input
                type="number"
                step="0.0001"
                value={form.home_lon}
                onChange={(e) => setForm({ ...form, home_lon: +e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
          </div>
        </section>

        {/* Intervals.icu */}
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
          <h2 className="font-medium text-gray-300">Intervals.icu</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Athlete ID</label>
              <input
                type="text"
                value={form.intervals_athlete_id}
                onChange={(e) =>
                  setForm({ ...form, intervals_athlete_id: e.target.value })
                }
                placeholder="iXXXXX"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">API Key</label>
              <input
                type="password"
                value={form.intervals_api_key}
                onChange={(e) =>
                  setForm({ ...form, intervals_api_key: e.target.value })
                }
                placeholder="Votre cle API"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50"
          >
            <RefreshCw size={16} className={syncMutation.isPending ? "animate-spin" : ""} />
            Synchroniser depuis Intervals.icu
          </button>
          {syncMutation.isError && (
            <p className="text-red-400 text-sm">{String(syncMutation.error)}</p>
          )}
          {syncMutation.isSuccess && (
            <p className="text-green-400 text-sm">Profil synchronise</p>
          )}
        </section>

        <button
          type="submit"
          disabled={updateMutation.isPending}
          className="flex items-center gap-2 px-6 py-2 bg-green-600 hover:bg-green-700 rounded font-medium disabled:opacity-50"
        >
          <Save size={16} />
          Sauvegarder
        </button>
        {updateMutation.isSuccess && (
          <p className="text-green-400 text-sm">Profil sauvegarde</p>
        )}
      </form>
    </div>
  );
}
