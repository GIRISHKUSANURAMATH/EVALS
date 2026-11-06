import { Check, Flag, RotateCcw, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Category, Example } from "../api/types";
import QualityFactors from "../components/QualityFactors";
import { Badge, Card, EmptyState, ErrorBanner, Mono, PageHeader, Pagination, Select, Spinner, TextBlock, fmt, truncate } from "../components/ui";
import { useAsync, useLocalStorage } from "../hooks/useAsync";

const PAGE_SIZE = 20;
const ACTION_LABELS: Record<string, string> = { approve: "Approved", reject: "Rejected", flag: "Flagged as uncertain", reset: "Reset to pending" };

export default function ReviewPage() {
  const [params, setParams] = useSearchParams();
  const datasets = useAsync(() => api.datasets(), []);
  const cats = useAsync(() => api.categories(), []);
  const datasetId = params.get("dataset") ?? datasets.data?.items[0]?.id ?? "";
  const [status, setStatus] = useState("pending");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string>();
  // Confirmation of the last action, kept at page level because the reviewed example may leave the filtered list.
  const [notice, setNotice] = useState<string>();
  const list = useAsync(
    () => (datasetId ? api.examples(datasetId, { page, page_size: PAGE_SIZE, status, category, search: query }) : Promise.resolve(undefined)),
    [datasetId, page, status, category, query],
  );

  // Keep the editor in sync with the list: the selected example must always be one the list shows.
  // When the list is empty (a review moved the last match out of the filter, or nothing matches), clear it.
  useEffect(() => {
    if (!list.data) return;
    const items = list.data.items;
    if (!items.length) {
      if (selectedId !== undefined) setSelectedId(undefined);
    } else if (!items.some((e) => e.id === selectedId)) {
      setSelectedId(items[0].id);
    }
  }, [list.data, selectedId]);

  function onReviewed(message: string) {
    setNotice(message);
    list.reload();
  }

  if (datasets.loading && !datasets.data) return <Spinner />;
  if (datasets.error) return <ErrorBanner message={datasets.error} />;
  if (!datasets.data?.items.length) {
    return (
      <div>
        <PageHeader title="Human Review" />
        <EmptyState title="No datasets to review" body="Generate a dataset first on the Generated Datasets page." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Human Review"
        subtitle="Approve, reject or flag examples. Edit expected outputs and categories. Every action is recorded in the annotation history."
        actions={
          <div className="w-64">
            <Select
              ariaLabel="Dataset"
              value={datasetId}
              onChange={(v) => { setParams({ dataset: v }); setPage(1); setSelectedId(undefined); setNotice(undefined); }}
              options={datasets.data.items.map((d) => ({ value: d.id, label: `${d.name} (${d.example_count})` }))}
            />
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <div className="mb-3 space-y-2">
            <div className="flex gap-1" role="tablist" aria-label="Review status">
              {["pending", "approved", "rejected", "flagged", ""].map((s) => (
                <button key={s || "all"} role="tab" aria-selected={status === s} onClick={() => { setStatus(s); setPage(1); setNotice(undefined); }} className={`rounded-md px-2.5 py-1 text-xs ${status === s ? "bg-ink-700 text-ink-100" : "text-ink-400 hover:text-ink-200"}`}>
                  {s || "all"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <form onSubmit={(e) => { e.preventDefault(); setQuery(search); setPage(1); }} className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-500" />
                <input className="input pl-8" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search examples" />
              </form>
              <Select ariaLabel="Category filter" value={category} onChange={(v) => { setCategory(v); setPage(1); }} options={[{ value: "", label: "All categories" }, ...(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))]} />
            </div>
          </div>
          {notice && <div className="mb-2 rounded-md bg-ok/10 px-3 py-2 text-xs text-ok" role="status" data-testid="review-notice">{notice}</div>}
          {list.error && <ErrorBanner message={list.error} />}
          {list.loading && !list.data ? <Spinner /> : list.data?.items.length === 0 ? (
            <EmptyState title={`No ${status || ""} examples`} />
          ) : (
            <>
              <ul className="max-h-[62vh] space-y-1 overflow-auto pr-1" data-testid="example-list">
                {list.data?.items.map((e) => (
                  <li key={e.id}>
                    <button onClick={() => setSelectedId(e.id)} className={`w-full rounded-lg px-3 py-2 text-left ${e.id === selectedId ? "bg-ink-800 ring-1 ring-ink-600" : "hover:bg-ink-850"}`}>
                      <div className="flex items-center gap-1.5">
                        <Badge tone="pending">{e.category}</Badge>
                        {e.failure_type && <Badge tone={e.failure_evidence}>{e.failure_type}</Badge>}
                        <span className="ml-auto font-mono text-[11px] text-ink-400">{e.quality_score.toFixed(2)}</span>
                      </div>
                      <div className="mt-1 text-sm text-ink-200">{truncate(e.input, 90) || <i className="text-ink-500">(empty input)</i>}</div>
                    </button>
                  </li>
                ))}
              </ul>
              {list.data && <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />}
            </>
          )}
        </Card>
        <div className="lg:col-span-3">
          {selectedId ? <ExampleEditor key={selectedId} id={selectedId} categories={cats.data ?? []} onChanged={onReviewed} /> : <EmptyState title="Select an example" />}
        </div>
      </div>
    </div>
  );
}

function ExampleEditor({ id, categories, onChanged }: { id: string; categories: Category[]; onChanged: (message: string) => void }) {
  const ex = useAsync(() => api.example(id), [id]);
  const [reviewer, setReviewer] = useLocalStorage("evals.reviewer", "reviewer");
  const [expected, setExpected] = useState<string>("");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState<string>();

  useEffect(() => {
    if (ex.data) {
      setExpected(ex.data.expected_output ?? "");
      setCategory(ex.data.category);
      setNote(ex.data.reviewer_notes);
    }
  }, [ex.data]);

  if (ex.loading && !ex.data) return <Spinner />;
  if (ex.error) return <ErrorBanner message={ex.error} />;
  const e: Example = ex.data!;
  const expectedChanged = expected !== (e.expected_output ?? "");

  async function act(action: string) {
    setBusy(true);
    setError(undefined);
    setSaved(undefined);
    try {
      await api.review(e.id, {
        action,
        reviewer,
        note: note !== e.reviewer_notes ? note : undefined,
        expected_output: expectedChanged ? expected : undefined,
        category: category !== e.category ? category : undefined,
      });
      setSaved(ACTION_LABELS[action]);
      ex.reload();
      onChanged(`${ACTION_LABELS[action]} ${e.source_trace_key}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveEdits() {
    setBusy(true);
    setError(undefined);
    try {
      await api.patchExample(e.id, {
        reviewer,
        expected_output: expectedChanged ? expected : undefined,
        category: category !== e.category ? category : undefined,
        reviewer_notes: note !== e.reviewer_notes ? note : undefined,
      });
      setSaved("Edits saved");
      ex.reload();
      onChanged(`Edits saved for ${e.source_trace_key}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="Example"
        actions={
          <div className="flex items-center gap-2">
            <Badge>{e.review_status}</Badge>
            <Mono>{truncate(e.source_trace_key, 18)}</Mono>
          </div>
        }
      >
        <div className="space-y-3">
          {e.system_prompt && <TextBlock label="System prompt" text={e.system_prompt} />}
          {e.context.length > 0 && (
            <div>
              <div className="label">Prior conversation ({e.context.length} messages)</div>
              <div className="max-h-40 space-y-1 overflow-auto rounded-lg border border-ink-800 p-2 text-xs">
                {e.context.map((m, i) => (
                  <div key={i}><span className={`font-mono ${m.role === "user" ? "text-accent" : "text-info"}`}>{m.role}</span> <span className="text-ink-300">{truncate(m.content, 300)}</span></div>
                ))}
              </div>
            </div>
          )}
          <TextBlock label="Input" text={e.input} />
          <TextBlock label="Observed production output" text={e.actual_output} />
          {e.failure_type && (
            <div className="flex items-center gap-2 text-xs">
              <span className="label mb-0">Failure</span>
              <Badge tone={e.failure_evidence}>{e.failure_evidence}</Badge>
              <span className="font-mono text-ink-200">{e.failure_type}</span>
              <span className="text-ink-500">confidence {e.confidence_score.toFixed(2)}</span>
            </div>
          )}
          <div>
            <div className="label flex items-center gap-2">
              Expected output <Badge tone={e.expected_output_source}>{e.expected_output_source}</Badge>
            </div>
            <textarea className="input font-mono text-xs" rows={4} value={expected} onChange={(ev) => setExpected(ev.target.value)} placeholder="No reference answer. Write the ideal behaviour here." aria-label="Expected output" />
            <p className="mt-1 text-[11px] text-ink-500">{e.expected_output_rationale}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Select label="Category" value={category} onChange={setCategory} options={categories.map((c) => ({ value: c.name, label: c.name }))} />
            <label className="block sm:col-span-2"><span className="label">Notes</span><input className="input" value={note} onChange={(ev) => setNote(ev.target.value)} aria-label="Reviewer notes" /></label>
          </div>
          <label className="block w-48"><span className="label">Reviewer</span><input className="input" value={reviewer} onChange={(ev) => setReviewer(ev.target.value)} aria-label="Reviewer name" /></label>
          {error && <ErrorBanner message={error} />}
          {saved && <div className="text-xs text-ok">{saved}</div>}
          <div className="flex flex-wrap gap-2 border-t border-ink-800 pt-3">
            <button className="btn bg-ok/15 text-ok ring-1 ring-ok/30 hover:bg-ok/25" disabled={busy} onClick={() => act("approve")}><Check className="h-4 w-4" /> Approve</button>
            <button className="btn bg-observed/15 text-observed ring-1 ring-observed/30 hover:bg-observed/25" disabled={busy} onClick={() => act("reject")}><X className="h-4 w-4" /> Reject</button>
            <button className="btn bg-heuristic/15 text-heuristic ring-1 ring-heuristic/30 hover:bg-heuristic/25" disabled={busy} onClick={() => act("flag")}><Flag className="h-4 w-4" /> Flag uncertain</button>
            <button className="btn-ghost" disabled={busy} onClick={() => act("reset")}><RotateCcw className="h-4 w-4" /> Reset</button>
            <button className="btn-ghost ml-auto" disabled={busy} onClick={saveEdits}>Save edits only</button>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card><QualityFactors factors={e.quality_factors} score={e.quality_score} /></Card>
        <Card title="Annotation history">
          {e.annotations?.length ? (
            <ol className="space-y-2 text-xs">
              {e.annotations.slice().reverse().map((a) => (
                <li key={a.id} className="rounded-lg border border-ink-800 p-2">
                  <div className="flex items-center justify-between"><span className="font-mono text-ink-200">{a.action}</span><span className="text-ink-500">{fmt.date(a.created_at)}</span></div>
                  <div className="text-ink-400">by {a.reviewer}{a.note && ` — “${truncate(a.note, 80)}”`}</div>
                  <div className="mt-1 font-mono text-[10px] text-ink-500">{Object.keys(a.new_values).join(", ")}</div>
                </li>
              ))}
            </ol>
          ) : <div className="text-xs text-ink-500">No review actions yet.</div>}
        </Card>
      </div>
    </div>
  );
}
