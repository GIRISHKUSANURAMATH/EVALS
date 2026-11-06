export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProcessingEvent {
  id: number;
  stage: string;
  status: string;
  message: string;
  duration_ms: number;
  details: Record<string, unknown>;
  created_at: string;
}

export interface Job {
  id: string;
  filename: string;
  file_format: string;
  source: string;
  status: string;
  file_size_bytes: number;
  total_records: number;
  valid_records: number;
  invalid_records: number;
  trace_count: number;
  redaction_counts: Record<string, number>;
  stats: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  events?: ProcessingEvent[];
}

export interface Failure {
  id: number;
  trace_id: string;
  job_id: string;
  failure_type: string;
  evidence: "observed" | "heuristic";
  severity: string;
  detail: string;
  turn_index: number | null;
  trace_key?: string;
  input_text?: string;
}

export interface TraceSummary {
  id: string;
  job_id: string;
  trace_key: string;
  start_time: string | null;
  turn_count: number;
  total_latency_ms: number | null;
  total_tokens: number | null;
  models: string[];
  status: "ok" | "failed" | "warning";
  is_complete: boolean;
  has_missing_response: boolean;
  input_text: string;
  output_text: string | null;
  failure_types: string[];
  duplicate_of_id: string | null;
  duplicate_method: string | null;
  duplicate_score: number;
  duplicate_group_size: number;
  cluster_id: string | null;
}

export interface Turn {
  index: number;
  timestamp: string | null;
  user_input: string | null;
  assistant_response: string | null;
  model: string | null;
  latency_ms: number | null;
  status: string | null;
  error_type: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export interface TraceDetail extends TraceSummary {
  end_time: string | null;
  system_prompt: string | null;
  conversation: Turn[];
  metadata: Record<string, unknown>;
  failures: Failure[];
}

export interface FailureSummary {
  total: number;
  observed: number;
  heuristic: number;
  by_type: { failure_type: string; count: number; evidence: string; description: string }[];
  by_severity: Record<string, number>;
}

export interface Cluster {
  id: string;
  job_id: string;
  label: string;
  method: string;
  size: number;
  top_terms: string[];
  failure_rate: number;
  representative_trace_id: string | null;
  created_at: string;
  representative?: TraceSummary | null;
  samples?: TraceSummary[];
}

export interface DatasetVersion {
  id: string;
  version_number: number;
  example_count: number;
  approved_count: number;
  notes: string;
  checksum: string;
  created_at: string;
}

export interface DatasetStats {
  total: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_expected_source: Record<string, number>;
  avg_quality: number;
  category_coverage: number;
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
  source_job_ids: string[];
  generation_config: Record<string, unknown>;
  current_version: number;
  created_at: string;
  updated_at: string;
  example_count?: number;
  approved_count?: number;
  stats?: DatasetStats;
  versions?: DatasetVersion[];
}

export interface QualityFactor {
  name: string;
  value: number;
  weight: number;
  explanation: string;
}

export interface Annotation {
  id: number;
  action: string;
  reviewer: string;
  previous_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  note: string;
  created_at: string;
}

export type ReviewStatus = "pending" | "approved" | "rejected" | "flagged";

export interface Example {
  id: string;
  dataset_id: string;
  source_trace_id: string | null;
  source_trace_key: string;
  source_job_id: string;
  source_timestamp: string | null;
  input: string;
  system_prompt: string | null;
  context: { role: string; content: string }[];
  actual_output: string | null;
  expected_output: string | null;
  expected_output_source: "none" | "candidate" | "human_approved";
  expected_output_rationale: string;
  category: string;
  failure_type: string | null;
  failure_evidence: "observed" | "heuristic" | "none";
  metadata: Record<string, unknown>;
  confidence_score: number;
  quality_score: number;
  quality_factors: QualityFactor[];
  review_status: ReviewStatus;
  reviewer_notes: string;
  created_at: string;
  updated_at: string;
  annotations?: Annotation[];
}

export interface Category {
  id: number;
  name: string;
  description: string;
  is_builtin: boolean;
}

export interface RuntimeSettings {
  latency_threshold_ms: number;
  similarity_threshold: number;
  semantic_dedup: boolean;
  clustering_method: "kmeans" | "dbscan";
  max_clusters: number;
  use_embeddings: boolean;
  redact_ip_addresses: boolean;
  sensitive_fields: string[];
  custom_patterns: Record<string, string>;
  repeated_failure_min: number;
}

export interface Metrics {
  total_logs: number;
  valid_logs: number;
  total_traces: number;
  candidate_examples: number;
  approved_examples: number;
  detected_failures: number;
  failed_traces: number;
  duplicate_percentage: number;
  average_latency_ms: number | null;
  processing_success_rate: number | null;
  jobs_total: number;
  clusters: number;
  failures_by_type: { name: string; observed: number; heuristic: number }[];
  examples_by_category: { name: string; count: number }[];
  review_breakdown: Record<string, number>;
  trace_status: Record<string, number>;
  latency_histogram: { bucket: string; count: number }[];
  recent_jobs: { id: string; filename: string; status: string; total_records: number; trace_count: number; created_at: string }[];
}

export interface Health {
  status: string;
  version: string;
  database: string;
  embeddings_available: boolean;
  admin_enabled: boolean;
}
