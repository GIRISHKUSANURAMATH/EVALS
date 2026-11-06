import { Search, X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorBanner, Mono, PageHeader, Pagination, Select, Spinner, TextBlock, fmt, truncate } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const PAGE_SIZE = 25;

export default function TracesPage() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const status = params.get("status") ?? "";
  const duplicates = params.get("duplicates") ?? "";
  const failureType = params.get("failure_type") ?? "";
  const clusterId = params.get("cluster_id") ?? "";
  const selected = params.get("trace");

  const list = useAsync(
    () => api.traces({ page, page_size: PAGE_SIZE, status, duplicates, failure_type: failureType, cluster_id: clusterId, search: query }),
    [page, status, duplicates, failureType, clusterId, query],
  );

  function setParam(k: string, v: string) {
    setMany({ [k]: v });
  }

  function setMany(values: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(values)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next);
    if (!("trace" in values)) setPage(1);
  }

  return (
    <div>
      <PageHeader title="Traces Explorer" subtitle="Reconstructed interactions. Multi-turn conversations, paired request/response events and incomplete traces." />
      <Card>
        <div className="mb-3 grid gap-2 md:grid-cols-5">
          <form
            className="relative md:col-span-2"
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(search);
              setPage(1);
            }}
          >
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-500" />
            <input className="input pl-8" placeholder="Search input, output or trace id" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search traces" />
          </form>
          <Select ariaLabel="Status filter" value={status} onChange={(v) => setParam("status", v)} options={[{ value: "", label: "All statuses" }, { value: "ok", label: "ok" }, { value: "warning", label: "warning" }, { value: "failed", label: "failed" }]} />
          <Select ariaLabel="Duplicate filter" value={duplicates} onChange={(v) => setParam("duplicates", v)} options={[{ value: "", label: "Incl. duplicates" }, { value: "exclude", label: "Unique only" }, { value: "only", label: "Duplicates only" }]} />
          <div className="flex items-center gap-2 text-xs text-ink-400">
            {(failureType || clusterId) && (
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setMany({ failure_type: "", cluster_id: "" })}>
                <X className="h-3 w-3" /> {failureType || "cluster filter"}
              </button>
            )}
          </div>
        </div>
        {list.error && <ErrorBanner message={list.error} onRetry={list.reload} />}
        {list.loading && !list.data ? (
          <Spinner />
        ) : list.data && list.data.items.length === 0 ? (
          <EmptyState title="No traces match" body="Adjust filters or ingest some logs first." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-ink-800">
                <tr>
                  <th className="th">Trace</th>
                  <th className="th">Input</th>
                  <th className="th">Turns</th>
                  <th className="th">Latency</th>
                  <th className="th">Status</th>
                  <th className="th">Signals</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {list.data?.items.map((t) => (
                  <tr key={t.id} className="cursor-pointer hover:bg-ink-850" onClick={() => setParam("trace", t.id)}>
                    <td className="td"><Mono>{truncate(t.trace_key, 22)}</Mono>{t.duplicate_of_id && <div className="mt-1"><Badge tone="pending">{`dup · ${t.duplicate_method}`}</Badge></div>}</td>
                    <td className="td max-w-md text-ink-200">{truncate(t.input_text, 90) || <span className="italic text-ink-500">(empty)</span>}</td>
                    <td className="td font-mono text-xs">{t.turn_count}</td>
                    <td className="td font-mono text-xs">{fmt.ms(t.total_latency_ms)}</td>
                    <td className="td"><Badge>{t.status}</Badge></td>
                    <td className="td"><div className="flex max-w-xs flex-wrap gap-1">{t.failure_types.map((f) => <Badge key={f} tone="pending">{f}</Badge>)}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.data && <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />}
          </div>
        )}
      </Card>
      {selected && <TraceDrawer id={selected} onClose={() => setParam("trace", "")} />}
    </div>
  );
}

export function TraceDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useAsync(() => api.trace(id), [id]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto border-l border-ink-700 bg-ink-900 p-6 animate-rise" onClick={(e) => e.stopPropagation()} aria-label="Trace detail">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-mono text-sm text-ink-200">{t.data?.trace_key ?? "Trace"}</h2>
          <button className="btn-ghost px-2" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        {t.loading && <Spinner />}
        {t.error && <ErrorBanner message={t.error} />}
        {t.data && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge>{t.data.status}</Badge>
              <Badge tone={t.data.is_complete ? "ok" : "warning"}>{t.data.is_complete ? "complete" : "incomplete"}</Badge>
              {t.data.models.map((m) => <Badge key={m} tone="pending">{m}</Badge>)}
              {t.data.duplicate_group_size > 1 && <Badge tone="pending">{`group of ${t.data.duplicate_group_size}`}</Badge>}
            </div>
            {t.data.failures.length > 0 && (
              <div className="space-y-1.5">
                <div className="label">Failure signals</div>
                {t.data.failures.map((f) => (
                  <div key={f.id} className="flex items-start gap-2 rounded-lg border border-ink-800 p-2 text-xs">
                    <Badge tone={f.evidence}>{f.evidence}</Badge>
                    <div>
                      <div className="font-mono text-ink-200">{f.failure_type}{f.turn_index !== null && <span className="text-ink-500"> · turn {f.turn_index + 1}</span>}</div>
                      <div className="text-ink-400">{f.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {t.data.system_prompt && <TextBlock label="System prompt" text={t.data.system_prompt} />}
            <div>
              <div className="label">Conversation ({t.data.conversation.length} turns)</div>
              <ol className="space-y-3">
                {t.data.conversation.map((turn) => (
                  <li key={turn.index} className="rounded-lg border border-ink-800 p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                      <span className="font-mono">#{turn.index + 1}</span>
                      <span>{fmt.date(turn.timestamp)}</span>
                      <span>{fmt.ms(turn.latency_ms)}</span>
                      {turn.status && <Badge>{turn.status}</Badge>}
                    </div>
                    <div className="space-y-2 text-sm">
                      <div><span className="mr-2 font-mono text-xs text-accent">user</span><span className="whitespace-pre-wrap text-ink-200">{turn.user_input ?? <i className="text-ink-500">(none)</i>}</span></div>
                      <div><span className="mr-2 font-mono text-xs text-info">assistant</span><span className="whitespace-pre-wrap text-ink-300">{turn.assistant_response === null ? <i className="text-ink-500">(no response logged)</i> : turn.assistant_response === "" ? <i className="text-observed">(empty response)</i> : truncate(turn.assistant_response, 1200)}</span></div>
                      {(turn.error_type || turn.error_message) && <div className="font-mono text-xs text-observed">{turn.error_type} {turn.error_message}</div>}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
