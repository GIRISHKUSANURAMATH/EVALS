import { vi } from "vitest";
import type { Dataset, Example, Metrics } from "../api/types";

type Handler = (url: URL, init?: RequestInit) => unknown;

export interface Call {
  method: string;
  url: URL;
  body: unknown;
}

export function mockFetch(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = init?.body;
    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch {
        /* keep raw */
      }
    }
    calls.push({ method, url, body });
    const key = Object.keys(routes).find((k) => {
      const [m, path] = k.split(" ");
      return m === method && new RegExp(`^${path}$`).test(url.pathname);
    });
    if (!key) return new Response(JSON.stringify({ detail: `no mock for ${method} ${url.pathname}` }), { status: 404 });
    const result = routes[key](url, init);
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export const health = { status: "ok", version: "1.0.0", database: "ok", embeddings_available: false, admin_enabled: true };

export const emptyMetrics: Metrics = {
  total_logs: 0, valid_logs: 0, total_traces: 0, candidate_examples: 0, approved_examples: 0, detected_failures: 0,
  failed_traces: 0, duplicate_percentage: 0, average_latency_ms: null, processing_success_rate: null, jobs_total: 0,
  clusters: 0, failures_by_type: [], examples_by_category: [], review_breakdown: {}, trace_status: {},
  latency_histogram: [], recent_jobs: [],
};

export const metrics: Metrics = {
  ...emptyMetrics,
  total_logs: 286, valid_logs: 282, total_traces: 260, candidate_examples: 82, approved_examples: 5,
  detected_failures: 111, failed_traces: 60, duplicate_percentage: 65.0, average_latency_ms: 2332.9,
  processing_success_rate: 100, jobs_total: 1, clusters: 7,
  failures_by_type: [{ name: "timeout", observed: 9, heuristic: 0 }],
  examples_by_category: [{ name: "latency", count: 10 }],
  trace_status: { ok: 200, failed: 60 },
  latency_histogram: [{ bucket: "0-0.5s", count: 3 }],
  recent_jobs: [{ id: "j1", filename: "production_logs.jsonl", status: "completed", total_records: 286, trace_count: 260, created_at: "2026-11-01T10:00:00" }],
};

export const dataset: Dataset = {
  id: "11111111-1111-1111-1111-111111111111", name: "eval-set", description: "", source_job_ids: ["j1"],
  generation_config: {}, current_version: 1, created_at: "2026-11-01T10:00:00", updated_at: "2026-11-01T10:00:00",
  example_count: 2, approved_count: 0,
};

export const example: Example = {
  id: "ex1", dataset_id: dataset.id, source_trace_id: "t1", source_trace_key: "tr_00001", source_job_id: "j1",
  source_timestamp: "2026-09-01T08:00:00", input: "How do I reset my password?", system_prompt: "Be helpful",
  context: [], actual_output: "", expected_output: null, expected_output_source: "none",
  expected_output_rationale: "No reference answer available.", category: "error_handling",
  failure_type: "empty_response", failure_evidence: "observed", metadata: {}, confidence_score: 0.95,
  quality_score: 0.81, quality_factors: [{ name: "completeness", value: 0.75, weight: 0.2, explanation: "missing: expected_output" }],
  review_status: "pending", reviewer_notes: "", created_at: "", updated_at: "", annotations: [],
};

export const categories = ["correctness", "latency", "error_handling", "safety"].map((name, i) => ({ id: i + 1, name, description: "", is_builtin: true }));

export const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 25 });
