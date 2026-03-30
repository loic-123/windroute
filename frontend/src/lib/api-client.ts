const BACKEND_BASE = "/api/backend";

async function fetchAPI<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${BACKEND_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API error ${res.status}: ${error}`);
  }

  return res.json();
}

export const api = {
  // Athlete
  getProfile: () => fetchAPI<import("@/types/api").AthleteProfile>("/athlete/profile"),
  updateProfile: (data: Partial<import("@/types/api").AthleteProfile>) =>
    fetchAPI<import("@/types/api").AthleteProfile>("/athlete/profile", {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  syncProfile: (apiKey?: string, athleteId?: string) =>
    fetchAPI<import("@/types/api").AthleteProfile>("/athlete/sync", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, athlete_id: athleteId }),
    }),

  // Workouts
  getWorkouts: (dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    return fetchAPI<import("@/types/api").Workout[]>(
      `/workouts?${params.toString()}`
    );
  },
  getWorkout: (id: string) =>
    fetchAPI<import("@/types/api").Workout>(`/workouts/${id}`),
  syncWorkouts: (dateFrom?: string, dateTo?: string) =>
    fetchAPI<import("@/types/api").Workout[]>("/workouts/sync", {
      method: "POST",
      body: JSON.stringify({ date_from: dateFrom, date_to: dateTo }),
    }),

  // Weather
  getWeather: (lat: number, lon: number, hours?: number) =>
    fetchAPI<import("@/types/api").WeatherForecast>(
      `/weather?lat=${lat}&lon=${lon}&hours=${hours || 6}`
    ),

  // Route generation
  generateRoutes: (request: import("@/types/api").GenerateRequest) =>
    fetchAPI<import("@/types/api").GenerationJob>("/routes/generate", {
      method: "POST",
      body: JSON.stringify(request),
    }),
  getJobStatus: (jobId: string) =>
    fetchAPI<import("@/types/api").GenerationJob>(`/routes/jobs/${jobId}`),
  getRoutes: (limit?: number) =>
    fetchAPI<import("@/types/api").RouteData[]>(`/routes?limit=${limit || 20}`),
  getRoute: (id: string) =>
    fetchAPI<import("@/types/api").RouteData>(`/routes/${id}`),
  selectRoute: (id: string) =>
    fetchAPI<{ status: string }>(`/routes/${id}/select`, { method: "PUT" }),
  deleteRoute: (id: string) =>
    fetchAPI<{ status: string }>(`/routes/${id}`, { method: "DELETE" }),
  getGpxUrl: (id: string) => `${BACKEND_BASE}/routes/${id}/gpx`,
};
