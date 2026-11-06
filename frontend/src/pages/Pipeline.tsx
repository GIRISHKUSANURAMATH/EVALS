import { CheckCircle2, CircleX } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, fmt } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const STAGE_LABELS: Record<string, string> = {
  validation: "File validation",
  parsing: "Parsing",
  redaction: "PII & secret redaction",
  normalization: "Normalization",
  reconstruction: "Interaction reconstruction",
  failure_detection: "Failure & edge-case detection",
  deduplication: "Semantic deduplication",
  persistence: "Persistence",
  clustering: "Clustering",
  pipeline: "Pipeline",
};

export default function PipelinePage() {
  const [params, setParams] = useSearchParams();
  const jobs = useAsync(() => api.jobs(1, 50), []);
  const selectedId = params.get("job") ?? jobs.data?.items[0]?.id;
  const job = useAsync(() => (selectedId ? api.job(selectedId) : Promise.resolve(undefined)), [selectedId]);

  if (jobs.loading && !jobs.data) return <Spinner />;
  if (jobs.error) return <ErrorBanner message={jobs.error} onRetry={jobs.reload} />;
  const items = jobs.data?.items ?? [];

  return (
    <div>
      <PageHeader title="Processing Pipeline" subtitle="Every ingestion job records each stage with timing and outcome." />
      {items.length === 0 ? (
        <EmptyState title="No ingestion jobs yet" body="Upload a file or load the sample dataset to see the pipeline run." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title={`Jobs (${jobs.data?.total ?? 0})`}>
            <ul className="max-h-[70vh] space-y-1 overflow-auto">
              {items.map((j) => (
                <li key={j.id}>
                  <button
                    onClick={() => setParams({ job: j.id })}
                    className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${j.id === selectedId ? "bg-ink-800 ring-1 ring-ink-600" : "hover:bg-ink-850"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs text-ink-200">{j.filename}</span>
                      <Badge>{j.status}</Badge>
                    </div>
                    <div className="mt-0.5 text-[11px] text-ink-500">
                      {fmt.date(j.created_at)} · {j.file_format} · {fmt.int(j.total_records)} rec
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div className="space-y-4 lg:col-span-2">
            {job.loading && !job.data ? (
              <Spinner />
            ) : job.data ? (
              <>
                <Card title={job.data.filename} actions={<Badge>{job.data.status}</Badge>}>
                  {job.data.error_message && <ErrorBanner message={job.data.error_message} />}
                  <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                    {[
                      ["Size", fmt.bytes(job.data.file_size_bytes)],
                      ["Valid / total", `${fmt.int(job.data.valid_records)} / ${fmt.int(job.data.total_records)}`],
                      ["Traces", fmt.int(job.data.trace_count)],
                      ["Similarity backend", String(job.data.stats?.similarity_backend ?? "—")],
                    ].map(([k, v]) => (
                      <div key={k}>
                        <div className="text-ink-500">{k}</div>
                        <div className="font-mono text-sm text-ink-100">{v}</div>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card title="Stages">
                  <ol className="relative space-y-3 border-l border-ink-700 pl-6">
                    {(job.data.events ?? []).map((e) => (
                      <li key={e.id} className="relative">
                        <span className="absolute -left-[31px] top-0.5 grid h-5 w-5 place-items-center rounded-full bg-ink-900">
                          {e.status === "completed" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <CircleX className="h-4 w-4 text-observed" />}
                        </span>
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-sm font-medium text-ink-100">{STAGE_LABELS[e.stage] ?? e.stage}</span>
                          <span className="font-mono text-xs text-ink-500">{fmt.ms(e.duration_ms)}</span>
                        </div>
                        <div className="text-xs text-ink-400">{e.message}</div>
                        <StageDetails details={e.details} />
                      </li>
                    ))}
                  </ol>
                </Card>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function StageDetails({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([, v]) => v && typeof v === "object" && Object.keys(v as object).length);
  if (!entries.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {entries.flatMap(([k, v]) =>
        Array.isArray(v)
          ? [<Badge key={k} tone="pending">{`${k}: ${v.length}`}</Badge>]
          : Object.entries(v as Record<string, number>).map(([kk, vv]) => <Badge key={`${k}-${kk}`} tone="pending">{`${kk}: ${vv}`}</Badge>),
      )}
    </div>
  );
}
