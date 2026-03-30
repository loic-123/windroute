"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { WorkoutBlocks } from "@/components/workout/workout-blocks";
import { formatDuration, formatPower, BLOCK_LABELS } from "@/lib/utils";
import { Route } from "lucide-react";
import Link from "next/link";
import { use } from "react";

export default function WorkoutDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: workout, isLoading } = useQuery({
    queryKey: ["workout", id],
    queryFn: () => api.getWorkout(id),
  });

  if (isLoading) return <p className="text-gray-400">Chargement...</p>;
  if (!workout) return <p className="text-red-400">Seance non trouvee</p>;

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{workout.name}</h1>
          <p className="text-gray-400">
            {workout.planned_date} |{" "}
            {workout.duration_seconds
              ? formatDuration(workout.duration_seconds)
              : "—"}
          </p>
        </div>
        <Link
          href={`/generate?workout_id=${workout.id}`}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 rounded font-medium"
        >
          <Route size={16} />
          Generer une route
        </Link>
      </div>

      {workout.description && (
        <p className="text-gray-300">{workout.description}</p>
      )}

      {/* Visual blocks */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-400 mb-3">
          Structure de la seance
        </h2>
        <WorkoutBlocks blocks={workout.blocks} />
      </div>

      {/* Block detail table */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400">
              <th className="text-left px-4 py-3">#</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Duree</th>
              <th className="text-left px-4 py-3">Puissance</th>
              <th className="text-left px-4 py-3">% FTP</th>
            </tr>
          </thead>
          <tbody>
            {workout.blocks.map((block) => (
              <tr
                key={block.index}
                className="border-b border-gray-800/50 hover:bg-gray-800/30"
              >
                <td className="px-4 py-2 text-gray-500">{block.index + 1}</td>
                <td className="px-4 py-2">
                  {BLOCK_LABELS[block.block_type] || block.block_type}
                </td>
                <td className="px-4 py-2">
                  {formatDuration(block.duration_seconds)}
                </td>
                <td className="px-4 py-2 font-mono">
                  {formatPower(block.power_watts)}
                </td>
                <td className="px-4 py-2 text-gray-400">
                  {block.power_percent_ftp
                    ? `${block.power_percent_ftp.toFixed(0)}%`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
