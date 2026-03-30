"use client";

import type { WorkoutBlock } from "@/types/api";
import { BLOCK_COLORS, BLOCK_LABELS, formatDuration, formatPower } from "@/lib/utils";

interface WorkoutBlocksProps {
  blocks: WorkoutBlock[];
  maxPower?: number;
}

export function WorkoutBlocks({ blocks, maxPower }: WorkoutBlocksProps) {
  const max = maxPower || Math.max(...blocks.map((b) => b.power_watts), 1);

  return (
    <div className="space-y-1">
      <div className="flex items-end gap-0.5 h-32">
        {blocks.map((block) => {
          const height = (block.power_watts / max) * 100;
          const color = BLOCK_COLORS[block.block_type] || "#6b7280";
          const widthPercent = (block.duration_seconds / blocks.reduce((s, b) => s + b.duration_seconds, 0)) * 100;

          return (
            <div
              key={block.index}
              className="relative group"
              style={{
                width: `${Math.max(widthPercent, 0.5)}%`,
                height: `${Math.max(height, 5)}%`,
                backgroundColor: color,
                borderRadius: "2px 2px 0 0",
              }}
              title={`${BLOCK_LABELS[block.block_type] || block.block_type}: ${formatPower(block.power_watts)} x ${formatDuration(block.duration_seconds)}`}
            >
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block bg-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap z-10">
                {formatPower(block.power_watts)} — {formatDuration(block.duration_seconds)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex gap-3 text-xs text-gray-400">
        {Object.entries(BLOCK_LABELS).map(([type, label]) => {
          if (!blocks.some((b) => b.block_type === type)) return null;
          return (
            <div key={type} className="flex items-center gap-1">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: BLOCK_COLORS[type] }}
              />
              {label}
            </div>
          );
        })}
      </div>
    </div>
  );
}
