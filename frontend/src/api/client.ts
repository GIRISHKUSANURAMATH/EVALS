import type {
  Category,
  Cluster,
  Dataset,
  DatasetVersion,
  Example,
  Failure,
  FailureSummary,
  Health,
  Job,
  Metrics,
  Page,
  RuntimeSettings,
  TraceDetail,
  TraceSummary,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const API = `${BASE}/api/v1`;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const UNREACHABLE = "Cannot reach the EVALS backend. Is it running on port 8000?";

function hasDetail(body: unknown): boolean {
  return !!body && typeof body === "object" && "detail" in body;
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) {
      return d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}, base = API): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, init);
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  // The backend always answers errors with JSON {"detail": ...}. A 5xx without it comes from the
  // dev proxy or nginx when the backend is not running, so report it as unreachable.
  if (res.status >= 500 && !hasDetail(body)) throw new ApiError(res.status, `${UNREACHABLE} (HTTP ${res.status} from the proxy)`);
  if (!res.ok) throw new ApiError(res.status, detailMessage(body, `Request failed (${res.status})`));
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

const json = (method: string, body: unknown, headers: Record<string, string> = {}): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json", ...headers },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/health", {}, BASE),
  metrics: () => request<Metrics>("/dashboard/metrics"),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Job>("/ingestion/upload", { method: "POST", body: form });
  },
  loadSample: (name: string) => request<Job>(`/ingestion/sample${qs({ name })}`, { method: "POST" }),
  samples: () => request<{ name: string; filename: string; available: boolean }[]>("/ingestion/samples"),
  jobs: (page = 1, pageSize = 20) => request<Page<Job>>(`/ingestion/jobs${qs({ page, page_size: pageSize })}`),
  job: (id: string) => request<Job>(`/ingestion/jobs/${encodeURIComponent(id)}`),

  traces: (params: Record<string, string | number | undefined>) => request<Page<TraceSummary>>(`/traces${qs(params)}`),
  trace: (id: string) => request<TraceDetail>(`/traces/${encodeURIComponent(id)}`),
  failures: (params: Record<string, string | number | undefined>) => request<Page<Failure>>(`/failures${qs(params)}`),
  failureSummary: () => request<FailureSummary>("/failures/summary"),
  clusters: () => request<Page<Cluster>>("/clusters?page_size=200"),
  cluster: (id: string) => request<Cluster>(`/clusters/${encodeURIComponent(id)}`),

  datasets: () => request<Page<Dataset>>("/datasets?page_size=100"),
  dataset: (id: string) => request<Dataset>(`/datasets/${encodeURIComponent(id)}`),
  generate: (body: {
    name: string;
    description?: string;
    include_successful: boolean;
    exclude_duplicates: boolean;
    categories?: string[] | null;
    min_quality: number;
    max_examples: number;
  }) => request<Dataset>("/datasets/generate", json("POST", body)),
  createVersion: (id: string, notes: string) =>
    request<DatasetVersion>(`/datasets/${encodeURIComponent(id)}/versions`, json("POST", { notes })),
  deleteDataset: (id: string, adminKey: string) =>
    request<void>(`/datasets/${encodeURIComponent(id)}`, { method: "DELETE", headers: { "X-Admin-Key": adminKey } }),

  examples: (datasetId: string, params: Record<string, string | number | undefined>) =>
    request<Page<Example>>(`/datasets/${encodeURIComponent(datasetId)}/examples${qs(params)}`),
  example: (id: string) => request<Example>(`/examples/${encodeURIComponent(id)}`),
  patchExample: (id: string, body: { expected_output?: string; category?: string; reviewer_notes?: string; reviewer: string }) =>
    request<Example>(`/examples/${encodeURIComponent(id)}`, json("PATCH", body)),
  review: (id: string, body: { action: string; reviewer: string; note?: string; expected_output?: string; category?: string }) =>
    request<Example>(`/examples/${encodeURIComponent(id)}/review`, json("POST", body)),

  exportUrl: (
    datasetId: string,
    opts: { format: string; approved_only: boolean; categories?: string; statuses?: string; date_from?: string; date_to?: string },
  ) => `${API}/exports/${encodeURIComponent(datasetId)}${qs(opts)}`,
  exportPreview: async (url: string) => {
    const res = await fetch(url);
    if (!res.ok) throw new ApiError(res.status, detailMessage(safeJson(await res.text()), "Export failed"));
    return { text: await res.text(), count: Number(res.headers.get("X-Example-Count") ?? 0) };
  },

  categories: () => request<Category[]>("/categories"),
  createCategory: (name: string, description: string) =>
    request<Category>("/categories", json("POST", { name, description })),
  settings: () => request<RuntimeSettings>("/settings"),
  saveSettings: (s: Partial<RuntimeSettings>, adminKey: string) =>
    request<RuntimeSettings>("/settings", json("PUT", s, { "X-Admin-Key": adminKey })),
  redactionPreview: (text: string) =>
    request<{ redacted: string; counts: Record<string, number> }>("/privacy/preview", json("POST", { text })),
  reset: (adminKey: string) => request<void>("/admin/reset", { method: "POST", headers: { "X-Admin-Key": adminKey } }),
};
