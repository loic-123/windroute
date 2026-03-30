import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h${m.toString().padStart(2, "0")}`;
  if (m > 0) return `${m}min${s > 0 ? s.toString().padStart(2, "0") + "s" : ""}`;
  return `${s}s`;
}

export function formatDistance(km: number): string {
  return `${km.toFixed(1)} km`;
}

export function formatElevation(m: number): string {
  return `${Math.round(m)} m`;
}

export function formatPower(watts: number): string {
  return `${Math.round(watts)}W`;
}

export function formatScore(score: number): string {
  return `${(score * 100).toFixed(0)}%`;
}

export const BLOCK_COLORS: Record<string, string> = {
  warmup: "#22c55e",
  interval: "#ef4444",
  recovery: "#f97316",
  cooldown: "#6b7280",
  rest: "#a3a3a3",
};

export const BLOCK_LABELS: Record<string, string> = {
  warmup: "Echauffement",
  interval: "Intervalle",
  recovery: "Recuperation",
  cooldown: "Retour",
  rest: "Repos",
};
