"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface RouteElevationProps {
  coords: [number, number, number][] | null;
}

export function RouteElevation({ coords }: RouteElevationProps) {
  if (!coords || coords.length < 2) {
    return <p className="text-gray-500 text-sm">Pas de donnees d&apos;elevation</p>;
  }

  // Compute cumulative distance
  const data: { distance: number; elevation: number }[] = [];
  let cumDist = 0;

  for (let i = 0; i < coords.length; i++) {
    if (i > 0) {
      const dlat = coords[i][0] - coords[i - 1][0];
      const dlon = coords[i][1] - coords[i - 1][1];
      const dist = Math.sqrt(dlat * dlat + dlon * dlon) * 111000;
      cumDist += dist;
    }
    data.push({
      distance: +(cumDist / 1000).toFixed(2),
      elevation: Math.round(coords[i][2]),
    });
  }

  // Subsample if too many points
  const maxPoints = 500;
  const step = Math.max(1, Math.floor(data.length / maxPoints));
  const sampled = data.filter((_, i) => i % step === 0);

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={sampled}>
        <defs>
          <linearGradient id="eleGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="distance"
          tick={{ fontSize: 11, fill: "#9ca3af" }}
          tickFormatter={(v) => `${v} km`}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "#9ca3af" }}
          tickFormatter={(v) => `${v}m`}
          domain={["dataMin - 20", "dataMax + 20"]}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1f2937",
            border: "1px solid #374151",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(v: number) => [`${v}m`, "Altitude"]}
          labelFormatter={(v) => `${v} km`}
        />
        <Area
          type="monotone"
          dataKey="elevation"
          stroke="#22c55e"
          fill="url(#eleGrad)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
