import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorBanner, Mono, PageHeader, Pagination, Select, Spinner, Stat, truncate } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { TraceDrawer } from "./Traces";

const PAGE_SIZE = 25;

export default function FailuresPage() {
  const summary = useAsync(() => api.failureSummary(), []);
  const [evidence, setEvidence] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const [trace, setTrace] = useState<string>();
  const list = useAsync(() => api.failures({ page, page_size: PAGE_SIZE, evidence, failure_type: type }), [page, evidence, type]);

  if (summary.loading && !summary.data) return <Spinner />;
  if (summary.error) return <ErrorBanner message={summary.error} onRetry={summary.reload} />;
  const s = summary.data!;

  return (
    <div>
      <PageHeader
        title="Failure Analysis"
        subtitle="Observed failures are recorded in the logs themselves. Heuristic signals are rules of thumb that need human confirmation. EVALS never marks an answer wrong without evidence."
      />
      {s.total === 0 ? (
        <EmptyState title="No failures detected" body="Ingest logs to analyse failures." />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Total signals" value={s.total} />
            <Stat label="Observed" value={s.observed} tone="bad" hint="errors, timeouts, empty, user feedback…" />
            <Stat label="Heuristic" value={s.heuristic} tone="warn" hint="latency, repetition, refusals…" />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-5">
            <Card title="By failure type" className="lg:col-span-2">
              <ul className="space-y-1">
                {s.by_type.map((t) => {
                  const pct = (t.count / s.by_type[0].count) * 100;
                  return (
                    <li key={t.failure_type}>
                      <button className={`w-full rounded-lg px-2 py-1.5 text-left hover:bg-ink-850 ${type === t.failure_type ? "bg-ink-800" : ""}`} onClick={() => { setType(type === t.failure_type ? "" : t.failure_type); setPage(1); }} title={t.description}>
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="font-mono text-ink-200">{t.failure_type}</span>
                          <span className="flex items-center gap-2"><Badge tone={t.evidence}>{t.evidence}</Badge><span className="w-8 text-right font-mono text-ink-300">{t.count}</span></span>
                        </div>
                        <div className="mt-1 h-1 rounded bg-ink-800"><div className={`h-1 rounded ${t.evidence === "observed" ? "bg-observed" : "bg-heuristic"}`} style={{ width: `${pct}%` }} /></div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
            <Card title="Failure events" className="lg:col-span-3" actions={
              <div className="w-40"><Select ariaLabel="Evidence filter" value={evidence} onChange={(v) => { setEvidence(v); setPage(1); }} options={[{ value: "", label: "All evidence" }, { value: "observed", label: "Observed" }, { value: "heuristic", label: "Heuristic" }]} /></div>
            }>
              {list.error && <ErrorBanner message={list.error} />}
              {list.loading && !list.data ? <Spinner /> : (
                <>
                  <ul className="divide-y divide-ink-800">
                    {list.data?.items.map((f) => (
                      <li key={f.id} className="cursor-pointer py-2.5 hover:bg-ink-850/50" onClick={() => setTrace(f.trace_id)}>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={f.evidence}>{f.evidence}</Badge>
                          <span className="font-mono text-xs text-ink-100">{f.failure_type}</span>
                          <Badge tone={f.severity}>{f.severity}</Badge>
                          <Mono className="ml-auto">{truncate(f.trace_key, 20)}</Mono>
                        </div>
                        <div className="mt-1 text-sm text-ink-300">{truncate(f.input_text, 120)}</div>
                        <div className="text-xs text-ink-500">{f.detail}</div>
                      </li>
                    ))}
                  </ul>
                  {list.data && <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />}
                </>
              )}
              {type && <Link className="mt-2 inline-block text-xs text-accent hover:underline" to={`/traces?failure_type=${type}`}>Open {type} traces in explorer →</Link>}
            </Card>
          </div>
        </>
      )}
      {trace && <TraceDrawer id={trace} onClose={() => setTrace(undefined)} />}
    </div>
  );
}
