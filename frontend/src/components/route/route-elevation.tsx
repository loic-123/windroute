"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from "recharts";

export interface ElevationPoint {
  distance: number;
  elevation: number;
  lat: number;
  lon: number;
}

interface RouteElevationProps {
  coords: [number, number, number][] | null;
  onHover?: (point: { lat: number; lon: number } | null) => void;
}

export function buildElevationData(
  coords: [number, number, number][]
): ElevationPoint[] {
  const data: ElevationPoint[] = [];
  let cumDist = 0;

  for (let i = 0; i < coords.length; i++) {
    if (i > 0) {
      const dlat = (coords[i][0] - coords[i - 1][0]) * 111000;
      const dlon =
        (coords[i][1] - coords[i - 1][1]) *
        111000 *
        Math.cos((coords[i][0] * Math.PI) / 180);
      cumDist += Math.sqrt(dlat * dlat + dlon * dlon);
    }
    data.push({
      distance: +(cumDist / 1000).toFixed(3),
      elevation: Math.round(coords[i][2]),
      lat: coords[i][0],
      lon: coords[i][1],
    });
  }
  return data;
}

export function RouteElevation({ coords, onHover }: RouteElevationProps) {
  if (!coords || coords.length < 2) {
    return (
      <p className="text-gray-500 text-sm">Pas de donnees d&apos;elevation</p>
    );
  }

  const fullData = buildElevationData(coords);

  // Subsample at regular DISTANCE intervals (not index intervals)
  // so the cursor moves at constant speed on the map
  const maxPoints = 500;
  const totalDist = fullData[fullData.length - 1].distance;
  const distStep = totalDist / maxPoints;
  const sampled: ElevationPoint[] = [fullData[0]];
  let nextDist = distStep;
  for (let i = 1; i < fullData.length; i++) {
    if (fullData[i].distance >= nextDist) {
      sampled.push(fullData[i]);
      nextDist += distStep;
    }
  }
  // Always include last point
  if (sampled[sampled.length - 1] !== fullData[fullData.length - 1]) {
    sampled.push(fullData[fullData.length - 1]);
  }

  const handleMouseMove = (state: any) => {
    if (!onHover || !state?.activePayload?.[0]?.payload) return;
    const point = state.activePayload[0].payload as ElevationPoint;
    onHover({ lat: point.lat, lon: point.lon });
  };

  const handleMouseLeave = () => {
    onHover?.(null);
  };

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart
        data={sampled}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
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
