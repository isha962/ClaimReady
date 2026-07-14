import type {
  FacilityMetricsResponse,
  PatientDetailResponse,
  PatientListResponse,
  PipelineHealthResponse,
  SummaryResponse,
} from "@/lib/types";

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type FetchOptions = RequestInit & {
  searchParams?: Record<string, string | string[] | number | boolean | undefined>;
};

export async function fetchJson<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const url = new URL(path, DEFAULT_API_BASE_URL);
  if (options.searchParams) {
    for (const [key, value] of Object.entries(options.searchParams)) {
      if (value === undefined || value === null || value === "") {
        continue;
      }
      url.searchParams.set(key, Array.isArray(value) ? value[0] : String(value));
    }
  }

  const response = await fetch(url, {
    ...options,
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getApiBaseUrl() {
  return DEFAULT_API_BASE_URL;
}

export function getSummary() {
  return fetchJson<SummaryResponse>("/api/summary");
}

export function getPatients(searchParams: Record<string, string | string[] | number | boolean | undefined> = {}) {
  return fetchJson<PatientListResponse>("/api/patients", { searchParams });
}

export function getPatientDetail(patientExternalId: string) {
  return fetchJson<PatientDetailResponse>(`/api/patients/${encodeURIComponent(patientExternalId)}`);
}

export function getFacilities() {
  return fetchJson<FacilityMetricsResponse>("/api/facilities");
}

export function getPipelineHealth() {
  return fetchJson<PipelineHealthResponse>("/api/pipeline-health");
}
