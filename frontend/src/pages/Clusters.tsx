import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Cluster } from "../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Mono, PageHeader, Spinner, fmt, truncate } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export default function ClustersPage() {
  const list = useAsync(() => api.clusters(), []);
  const [selected, setSelected] = useState<string>();
  const items = list.data?.items ?? [];
  const activeId = selected ?? items[0]?.id;
  const detail = useAsync(() => (activeId ? api.cluster(activeId) : Promise.resolve(undefined)), [activeId]);

  if (list.loading && !list.data) return <Spinner />;
  if (list.error) return <ErrorBanner message={list.error} onRetry={list.reload} />;
  const max = Math.max(1, ...items.map((c) => c.size));

  return (
    <div>
      <PageHeader title="Semantic Clusters" subtitle="TF-IDF + K-means (or DBSCAN) over unique user inputs. Cluster sizes include duplicates folded into each representative." />
      {items.length === 0 ? (
        <EmptyState title="No clusters yet" body="Clusters are built automatically when logs are processed." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card title={`${items.length} clusters`} className="lg:col-span-2">
            <ul className="max-h-[70vh] space-y-1.5 overflow-auto pr-1">
              {items.map((c) => (
                <ClusterRow key={c.id} c={c} max={max} active={c.id === activeId} onClick={() => setSelected(c.id)} />
              ))}
            </ul>
          </Card>
          <div className="lg:col-span-3">
            {detail.loading && !detail.data ? <Spinner /> : detail.data && (
              <Card title={detail.data.label} actions={<Link to={`/traces?cluster_id=${detail.data.id}`} className="text-xs text-accent hover:underline">All traces →</Link>}>
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {detail.data.top_terms.map((t) => <Badge key={t} tone="candidate">{t}</Badge>)}
                </div>
                <div className="mb-4 grid grid-cols-3 gap-3 text-xs">
                  <div><div className="text-ink-500">Size</div><div className="font-mono text-lg">{detail.data.size}</div></div>
                  <div><div className="text-ink-500">Failure rate</div><div className="font-mono text-lg text-observed">{fmt.pct(detail.data.failure_rate * 100)}</div></div>
                  <div><div className="text-ink-500">Method</div><div className="font-mono text-lg">{detail.data.method}</div></div>
                </div>
                {detail.data.representative && (
                  <div className="mb-4 rounded-lg border border-accent/30 bg-accent/5 p-3">
                    <div className="label text-accent">Representative example</div>
                    <div className="text-sm text-ink-100">{detail.data.representative.input_text}</div>
                    <div className="mt-1 text-xs text-ink-400">{truncate(detail.data.representative.output_text, 200)}</div>
                  </div>
                )}
                <div className="label">Sample members</div>
                <ul className="divide-y divide-ink-800">
                  {detail.data.samples?.map((t) => (
                    <li key={t.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span className="text-ink-300">{truncate(t.input_text, 100)}</span>
                      <span className="flex shrink-0 items-center gap-2"><Mono>{truncate(t.trace_key, 14)}</Mono><Badge>{t.status}</Badge></span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ClusterRow({ c, max, active, onClick }: { c: Cluster; max: number; active: boolean; onClick: () => void }) {
  return (
    <li>
      <button onClick={onClick} className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${active ? "bg-ink-800 ring-1 ring-ink-600" : "hover:bg-ink-850"}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm text-ink-100">{c.label}</span>
          <span className="font-mono text-xs text-ink-400">{c.size}</span>
        </div>
        <div className="mt-1.5 flex h-1.5 overflow-hidden rounded bg-ink-800" title={`${(c.failure_rate * 100).toFixed(0)}% failed`}>
          <div className="bg-observed" style={{ width: `${(c.size / max) * c.failure_rate * 100}%` }} />
          <div className="bg-accent/70" style={{ width: `${(c.size / max) * (1 - c.failure_rate) * 100}%` }} />
        </div>
      </button>
    </li>
  );
}
