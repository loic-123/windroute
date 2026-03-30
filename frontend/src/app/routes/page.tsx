"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { formatDistance, formatElevation, formatScore } from "@/lib/utils";
import Link from "next/link";
import { MapPin, ChevronRight } from "lucide-react";

export default function RoutesPage() {
  const { data: routes, isLoading } = useQuery({
    queryKey: ["routes"],
    queryFn: () => api.getRoutes(),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Routes generees</h1>

      {isLoading ? (
        <p className="text-gray-400">Chargement...</p>
      ) : !routes || routes.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400">
            Aucune route generee.{" "}
            <Link href="/generate" className="text-blue-400 hover:underline">
              Generer une route
            </Link>
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {routes.map((route) => (
            <Link
              key={route.id}
              href={`/routes/${route.id}`}
              className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <h3 className="font-medium">{route.name}</h3>
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>{formatDistance(route.total_distance_km || 0)}</span>
                    <span>D+ {formatElevation(route.total_elevation_m || 0)}</span>
                    <span className="text-green-400 font-medium">
                      Score: {formatScore(route.overall_score || 0)}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        route.status === "completed"
                          ? "bg-green-900 text-green-400"
                          : route.status === "failed"
                          ? "bg-red-900 text-red-400"
                          : "bg-yellow-900 text-yellow-400"
                      }`}
                    >
                      Variante {route.variant}
                    </span>
                  </div>
                </div>
                <ChevronRight size={20} className="text-gray-500" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
