"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { WorkoutBlocks } from "@/components/workout/workout-blocks";
import { formatDuration } from "@/lib/utils";
import { RefreshCw, ChevronRight } from "lucide-react";
import Link from "next/link";

export default function WorkoutsPage() {
  const queryClient = useQueryClient();

  const { data: workouts, isLoading } = useQuery({
    queryKey: ["workouts"],
    queryFn: () => api.getWorkouts(),
  });

  const syncMutation = useMutation({
    mutationFn: () => api.syncWorkouts(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workouts"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Seances</h1>
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50"
        >
          <RefreshCw
            size={16}
            className={syncMutation.isPending ? "animate-spin" : ""}
          />
          Synchroniser
        </button>
      </div>

      {syncMutation.isError && (
        <p className="text-red-400 text-sm">{String(syncMutation.error)}</p>
      )}

      {isLoading ? (
        <p className="text-gray-400">Chargement...</p>
      ) : !workouts || workouts.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400">
            Aucune seance. Cliquez sur Synchroniser pour importer depuis
            Intervals.icu.
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {workouts.map((w) => (
            <Link
              key={w.id}
              href={`/workouts/${w.id}`}
              className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="font-medium">{w.name}</h3>
                  <p className="text-sm text-gray-400">
                    {w.planned_date} | {w.block_count} blocs |{" "}
                    {w.duration_seconds
                      ? formatDuration(w.duration_seconds)
                      : "—"}
                  </p>
                </div>
                <ChevronRight size={20} className="text-gray-500" />
              </div>
              {w.blocks.length > 0 && <WorkoutBlocks blocks={w.blocks} />}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
