import { GitCommitHorizontal } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Badge, Card, ErrorBanner, Mono, PageHeader, Pagination, Spinner, Stat, fmt, truncate } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const PAGE_SIZE = 15;

export default function DatasetDetailPage() {
  const { id = "" } = useParams();
  const ds = useAsync(() => api.dataset(id), [id]);
  const [page, setPage] = useState(1);
  const examples = useAsync(() => api.examples(id, { page, page_size: PAGE_SIZE }), [id, page]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (ds.loading && !ds.data) return <Spinner />;
  if (ds.error) return <ErrorBanner message={ds.error} />;
  const d = ds.data!;
  const s = d.stats!;
  const catData = Object.entries(s.by_category).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);

  async function snapshot() {
    setBusy(true);
    setError(undefined);
    try {
      await api.createVersion(id, notes);
      setNotes("");
      ds.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={d.name}
        subtitle={d.description || `Generated ${fmt.date(d.created_at)} from ${d.source_job_ids.length} ingestion job(s).`}
        actions={
          <>
            <Link className="btn-ghost" to={`/review?dataset=${d.id}`}>Review</Link>
            <Link className="btn-primary" to={`/export?dataset=${d.id}`}>Export</Link>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Examples" value={s.total} />
        <Stat label="Approved" value={s.by_status.approved ?? 0} tone="accent" />
        <Stat label="Pending" value={s.by_status.pending ?? 0} />
        <Stat label="Avg quality" value={s.avg_quality.toFixed(2)} />
        <Stat label="Category coverage" value={fmt.pct(s.category_coverage * 100)} hint="of built-in categories" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Category coverage" className="lg:col-span-2">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={catData}>
                <XAxis dataKey="name" stroke="#465066" fontSize={11} tickLine={false} axisLine={false} interval={0} angle={-25} textAnchor="end" height={55} />
                <YAxis stroke="#465066" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={30} />
                <Tooltip contentStyle={{ background: "#10141c", border: "1px solid #2a3344", borderRadius: 8, fontSize: 12 }} cursor={{ fill: "rgba(94,234,212,0.06)" }} />
                <Bar dataKey="count" fill="#5eead4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-400">
            Expected outputs:
            {Object.entries(s.by_expected_source).map(([k, v]) => <Badge key={k} tone={k}>{`${k}: ${v}`}</Badge>)}
          </div>
        </Card>
        <Card title="Versions & provenance">
          <ol className="space-y-2">
            {d.versions?.slice().reverse().map((v) => (
              <li key={v.id} className="flex gap-2 text-xs">
                <GitCommitHorizontal className="mt-0.5 h-4 w-4 text-accent" />
                <div>
                  <div className="text-ink-200">v{v.version_number} · {v.example_count} examples · {v.approved_count} approved</div>
                  <div className="text-ink-500">{fmt.date(v.created_at)} {v.notes && `— ${v.notes}`}</div>
                  <Mono className="text-[10px]">sha256 {v.checksum.slice(0, 12)}</Mono>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-3 flex gap-2">
            <input className="input" placeholder="Version notes" value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Version notes" />
            <button className="btn-ghost whitespace-nowrap" disabled={busy} onClick={snapshot}>Snapshot</button>
          </div>
          {error && <div className="mt-2"><ErrorBanner message={error} /></div>}
          <div className="mt-3 text-[11px] text-ink-500">Source jobs: {d.source_job_ids.map((j) => j.slice(0, 8)).join(", ")}</div>
        </Card>
      </div>
      <Card title="Examples" className="mt-4">
        {examples.loading && !examples.data ? <Spinner /> : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-ink-800"><tr><th className="th">Input</th><th className="th">Category</th><th className="th">Failure</th><th className="th">Expected</th><th className="th">Quality</th><th className="th">Status</th></tr></thead>
              <tbody className="divide-y divide-ink-800">
                {examples.data?.items.map((e) => (
                  <tr key={e.id}>
                    <td className="td max-w-sm text-ink-200">{truncate(e.input, 80)}</td>
                    <td className="td"><Badge tone="pending">{e.category}</Badge></td>
                    <td className="td">{e.failure_type ? <Badge tone={e.failure_evidence}>{e.failure_type}</Badge> : <span className="text-ink-500">—</span>}</td>
                    <td className="td"><Badge tone={e.expected_output_source}>{e.expected_output_source}</Badge></td>
                    <td className="td font-mono text-xs">{e.quality_score.toFixed(2)}</td>
                    <td className="td"><Badge>{e.review_status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {examples.data && <Pagination page={page} pageSize={PAGE_SIZE} total={examples.data.total} onPage={setPage} />}
          </div>
        )}
      </Card>
    </div>
  );
}
