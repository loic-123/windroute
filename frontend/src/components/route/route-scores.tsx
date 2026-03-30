"use client";

import { formatScore } from "@/lib/utils";
import { Wind, Mountain, Sun, Users } from "lucide-react";

interface RouteScoresProps {
  wind_score: number | null;
  climb_score: number | null;
  sunshine_score: number | null;
  heatmap_score: number | null;
  overall_score: number | null;
}

export function RouteScores({
  wind_score,
  climb_score,
  sunshine_score,
  heatmap_score,
  overall_score,
}: RouteScoresProps) {
  const scores = [
    { label: "Vent", value: wind_score, icon: Wind, color: "text-blue-400" },
    { label: "Montees", value: climb_score, icon: Mountain, color: "text-orange-400" },
    { label: "Soleil", value: sunshine_score, icon: Sun, color: "text-yellow-400" },
    { label: "Popularite", value: heatmap_score, icon: Users, color: "text-purple-400" },
  ];

  return (
    <div className="space-y-3">
      {/* Overall */}
      <div className="flex items-center justify-between">
        <span className="font-medium">Score global</span>
        <span className="text-lg font-bold text-green-400">
          {overall_score != null ? formatScore(overall_score) : "—"}
        </span>
      </div>

      {/* Individual scores */}
      {scores.map(({ label, value, icon: Icon, color }) => (
        <div key={label} className="flex items-center gap-3">
          <Icon size={16} className={color} />
          <span className="text-sm text-gray-400 flex-1">{label}</span>
          <div className="w-24 bg-gray-800 rounded-full h-2">
            <div
              className="h-2 rounded-full bg-gray-500"
              style={{
                width: `${(value ?? 0) * 100}%`,
                backgroundColor: value != null && value > 0.7 ? "#22c55e" : value != null && value > 0.4 ? "#f59e0b" : "#ef4444",
              }}
            />
          </div>
          <span className="text-sm w-10 text-right">
            {value != null ? formatScore(value) : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}
