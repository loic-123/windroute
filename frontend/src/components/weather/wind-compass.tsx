"use client";

interface WindCompassProps {
  direction_deg: number;
  speed_kmh: number;
  label: string;
}

export function WindCompass({ direction_deg, speed_kmh, label }: WindCompassProps) {
  // Arrow points in the direction wind blows TO (opposite of meteorological direction)
  const arrowRotation = direction_deg + 180;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-24 h-24">
        {/* Compass circle */}
        <div className="absolute inset-0 rounded-full border-2 border-gray-700" />

        {/* Cardinal labels */}
        <span className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 text-xs text-gray-500">N</span>
        <span className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1 text-xs text-gray-500">S</span>
        <span className="absolute top-1/2 right-0 translate-x-1 -translate-y-1/2 text-xs text-gray-500">E</span>
        <span className="absolute top-1/2 left-0 -translate-x-1 -translate-y-1/2 text-xs text-gray-500">O</span>

        {/* Wind arrow */}
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{ transform: `rotate(${arrowRotation}deg)` }}
        >
          <div className="w-0.5 h-10 bg-blue-400 relative">
            <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-0 h-0 border-l-[4px] border-r-[4px] border-b-[8px] border-l-transparent border-r-transparent border-b-blue-400" />
          </div>
        </div>
      </div>

      <div className="text-center">
        <p className="text-sm font-medium">{speed_kmh.toFixed(0)} km/h</p>
        <p className="text-xs text-gray-400">Vent {label}</p>
      </div>
    </div>
  );
}
