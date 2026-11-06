import { Activity, CheckCircle2, Copy, Database, FileStack, Gauge, ListTree, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, Stat, fmt } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

const AXIS = { stroke: "#465066", fontSize: 11, tickLine: false, axisLine: false };
const TOOLTIP = {
  contentStyle: { background: "#10141c", border: "1px solid #2a3344", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#c4cbd9" },
  cursor: { fill: "rgba(94,234,212,0.06)" },
};
const STATUS_COLORS: Record<string, string> = { ok: "#4ade80", warning: "#fbbf24", failed: "#fb7185" };

export default function DashboardPage() {
  const { data: m, error, loading, reload } = useAsync(() => api.metrics(), []);
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState<string>();

  async function loadSample() {
    setBusy(true);
    setLoadErr(undefined);
    try {
      await api.loadSample("production_logs");
      reload();
    } catch (e) {
      setLoadErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !m) return <Spinner />;
  if (error) return <ErrorBanner message={error} onRetry={reload} />;
  if (!m) return null;

  if (m.jobs_total === 0) {
    return (
      <div>
        <PageHeader title="Dashboard" subtitle="Turn production traffic into continuously improving evaluation datasets." />
        <div className="card animate-rise relative overflow-hidden p-10">
          <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-accent/10 blur-3xl" />
          <div className="max-w-xl">
            <Badge tone="candidate">empty workspace</Badge>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">No logs ingested yet</h2>
            <p className="mt-3 text-ink-300">
              Upload JSONL, JSON, CSV or key=value application logs. EVALS redacts PII, rebuilds conversations, flags failures with
              evidence levels, removes duplicates, clusters topics, and drafts evaluation examples for human review.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button className="btn-primary" onClick={loadSample} disabled={busy}>
                {busy ? "Processing sample…" : "Load synthetic sample data"}
              </button>
              <button className="btn-ghost" onClick={() => navigate("/upload")}>
                Upload your own logs
              </button>
            </div>
            {loadErr && <div className="mt-4"><ErrorBanner message={loadErr} /></div>}
            <ol className="mt-8 grid gap-2 font-mono text-xs text-ink-400 sm:grid-cols-3">
              {["ingest → redact", "reconstruct → detect", "dedup → cluster → generate"].map((s, i) => (
                <li key={s} className="rounded-lg border border-ink-700 px-3 py-2">
                  <span className="text-accent">0{i + 1}</span> {s}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    );
  }

  const statusData = Object.entries(m.trace_status).map(([name, value]) => ({ name, value }));
  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="All figures are computed live from the backend database."
        actions={
          <button className="btn-ghost" onClick={reload}>
            <Activity className="h-4 w-4" /> Refresh
          </button>
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Logs ingested" value={fmt.int(m.total_logs)} hint={`${fmt.int(m.valid_logs)} valid`} icon={<FileStack className="h-4 w-4" />} />
        <Stat label="Traces" value={fmt.int(m.total_traces)} hint={`${m.clusters} clusters`} icon={<ListTree className="h-4 w-4" />} />
        <Stat label="Candidate examples" value={fmt.int(m.candidate_examples)} tone="accent" icon={<Database className="h-4 w-4" />} />
        <Stat label="Approved examples" value={fmt.int(m.approved_examples)} icon={<CheckCircle2 className="h-4 w-4" />} />
        <Stat label="Detected failures" value={fmt.int(m.detected_failures)} hint={`${fmt.int(m.failed_traces)} failed traces`} tone="bad" icon={<ShieldAlert className="h-4 w-4" />} />
        <Stat label="Duplicate rate" value={fmt.pct(m.duplicate_percentage)} tone="warn" icon={<Copy className="h-4 w-4" />} />
        <Stat label="Avg latency" value={fmt.ms(m.average_latency_ms)} icon={<Gauge className="h-4 w-4" />} />
        <Stat label="Processing success" value={fmt.pct(m.processing_success_rate)} hint={`${m.jobs_total} jobs`} icon={<Activity className="h-4 w-4" />} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Failure signals by type" className="lg:col-span-2" actions={<Legend />}>
          {m.failures_by_type.length === 0 ? (
            <EmptyState title="No failures detected" />
          ) : (
            <div style={{ height: Math.max(240, m.failures_by_type.length * 26) }}>
              <ResponsiveContainer>
                <BarChart data={m.failures_by_type} layout="vertical" margin={{ left: 8, right: 12 }}>
                  <CartesianGrid horizontal={false} stroke="#1e2532" />
                  <XAxis type="number" {...AXIS} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" {...AXIS} width={170} interval={0} />
                  <Tooltip {...TOOLTIP} />
                  <Bar dataKey="observed" stackId="a" fill="#fb7185" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="heuristic" stackId="a" fill="#fbbf24" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Trace outcomes">
          <div className="h-56">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={80} paddingAngle={2} stroke="none" isAnimationActive={false}>
                  {statusData.map((d) => (
                    <Cell key={d.name} fill={STATUS_COLORS[d.name] ?? "#818cf8"} />
                  ))}
                </Pie>
                <Tooltip {...TOOLTIP} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex justify-center gap-4 text-xs text-ink-400">
            {statusData.map((d) => (
              <span key={d.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLORS[d.name] }} />
                {d.name} <span className="font-mono text-ink-200">{d.value}</span>
              </span>
            ))}
          </div>
        </Card>
        <Card title="Latency distribution">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={m.latency_histogram}>
                <CartesianGrid vertical={false} stroke="#1e2532" />
                <XAxis dataKey="bucket" {...AXIS} />
                <YAxis {...AXIS} allowDecimals={false} width={32} />
                <Tooltip {...TOOLTIP} />
                <Bar dataKey="count" fill="#5eead4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Examples by category">
          {m.examples_by_category.length === 0 ? (
            <EmptyState title="No examples yet" action={<Link className="btn-primary" to="/datasets">Generate a dataset</Link>} />
          ) : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={m.examples_by_category}>
                  <CartesianGrid vertical={false} stroke="#1e2532" />
                  <XAxis dataKey="name" {...AXIS} interval={0} angle={-30} textAnchor="end" height={60} />
                  <YAxis {...AXIS} allowDecimals={false} width={32} />
                  <Tooltip {...TOOLTIP} />
                  <Bar dataKey="count" fill="#818cf8" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Recent ingestion jobs" actions={<Link to="/pipeline" className="text-xs text-accent hover:underline">View all</Link>}>
          <ul className="divide-y divide-ink-800">
            {m.recent_jobs.map((j) => (
              <li key={j.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-mono text-xs text-ink-200">{j.filename}</div>
                  <div className="text-xs text-ink-500">
                    {fmt.int(j.total_records)} records · {fmt.int(j.trace_count)} traces
                  </div>
                </div>
                <Badge>{j.status}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex gap-3 text-xs text-ink-400">
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-observed" />observed</span>
      <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-heuristic" />heuristic</span>
    </div>
  );
}
