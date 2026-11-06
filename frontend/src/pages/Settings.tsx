import { KeyRound, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RuntimeSettings } from "../api/types";
import { Badge, Card, ErrorBanner, PageHeader, Select, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

function readKey(): string {
  try {
    return window.sessionStorage.getItem("evals.adminKey") ?? "";
  } catch {
    return "";
  }
}

export default function SettingsPage() {
  const health = useAsync(() => api.health(), []);
  const remote = useAsync(() => api.settings(), []);
  const cats = useAsync(() => api.categories(), []);
  const [s, setS] = useState<RuntimeSettings>();
  const [adminKey, setAdminKey] = useState(readKey);
  const [msg, setMsg] = useState<string>();
  const [error, setError] = useState<string>();
  const [newCat, setNewCat] = useState("");
  const [newCatDesc, setNewCatDesc] = useState("");
  const [patternName, setPatternName] = useState("");
  const [patternRegex, setPatternRegex] = useState("");
  const [previewText, setPreviewText] = useState("Contact priya@example.com or +91 98765 43210, key sk-test-abcdefghijklmnop1234");
  const [preview, setPreview] = useState<{ redacted: string; counts: Record<string, number> }>();

  useEffect(() => {
    if (remote.data) setS(remote.data);
  }, [remote.data]);

  function rememberKey(v: string) {
    setAdminKey(v);
    try {
      window.sessionStorage.setItem("evals.adminKey", v);
    } catch {
      /* ignore */
    }
  }

  async function guarded(fn: () => Promise<unknown>, ok: string) {
    setMsg(undefined);
    setError(undefined);
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (remote.loading && !s) return <Spinner />;
  if (remote.error) return <ErrorBanner message={remote.error} />;
  if (!s) return null;
  const set = <K extends keyof RuntimeSettings>(k: K, v: RuntimeSettings[K]) => setS({ ...s, [k]: v });

  return (
    <div>
      <PageHeader title="Settings" subtitle="Processing thresholds and redaction rules apply to subsequent uploads. Changing them requires the admin key." />
      {msg && <div className="mb-4 rounded-lg border border-ok/30 bg-ok/5 p-3 text-sm text-ok" role="status">{msg}</div>}
      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Admin access">
          <p className="mb-3 text-xs text-ink-400">
            Sensitive operations (changing settings, deleting datasets, resetting data) need <code className="font-mono text-ink-300">EVALS_ADMIN_API_KEY</code> set on the backend.
            Status: {health.data?.admin_enabled ? <Badge tone="ok">enabled</Badge> : <Badge tone="warning">disabled on server</Badge>}
          </p>
          <label className="block"><span className="label">Admin key (kept in this browser tab only)</span>
            <div className="relative"><KeyRound className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-500" /><input type="password" className="input pl-8" value={adminKey} onChange={(e) => rememberKey(e.target.value)} aria-label="Admin key" autoComplete="off" /></div>
          </label>
        </Card>
        <Card title="Processing">
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><span className="label">Latency threshold (ms)</span><input className="input" type="number" value={s.latency_threshold_ms} onChange={(e) => set("latency_threshold_ms", Number(e.target.value))} /></label>
            <label className="block"><span className="label">Similarity threshold</span><input className="input" type="number" step={0.01} min={0.5} max={1} value={s.similarity_threshold} onChange={(e) => set("similarity_threshold", Number(e.target.value))} /></label>
            <Select label="Clustering" value={s.clustering_method} onChange={(v) => set("clustering_method", v as RuntimeSettings["clustering_method"])} options={[{ value: "kmeans", label: "TF-IDF + K-means" }, { value: "dbscan", label: "TF-IDF + DBSCAN" }]} />
            <label className="block"><span className="label">Max clusters</span><input className="input" type="number" min={2} max={50} value={s.max_clusters} onChange={(e) => set("max_clusters", Number(e.target.value))} /></label>
            <label className="block"><span className="label">Repeated-failure minimum</span><input className="input" type="number" min={2} value={s.repeated_failure_min} onChange={(e) => set("repeated_failure_min", Number(e.target.value))} /></label>
          </div>
          <div className="mt-3 space-y-1.5 text-sm text-ink-300">
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.semantic_dedup} onChange={(e) => set("semantic_dedup", e.target.checked)} /> Similarity-based deduplication</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.use_embeddings} onChange={(e) => set("use_embeddings", e.target.checked)} /> Use sentence-transformers embeddings {health.data && !health.data.embeddings_available && <Badge tone="warning">not installed — falls back to TF-IDF</Badge>}</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.redact_ip_addresses} onChange={(e) => set("redact_ip_addresses", e.target.checked)} /> Redact IP addresses</label>
          </div>
          <button className="btn-primary mt-4" onClick={() => guarded(async () => setS(await api.saveSettings(s, adminKey)), "Settings saved")}>Save settings</button>
        </Card>
        <Card title="Redaction rules">
          <div className="label">Sensitive metadata fields (always masked)</div>
          <textarea className="input font-mono text-xs" rows={3} value={s.sensitive_fields.join(", ")} onChange={(e) => set("sensitive_fields", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} aria-label="Sensitive fields" />
          <div className="label mt-3">Custom patterns</div>
          <ul className="mb-2 space-y-1">
            {Object.entries(s.custom_patterns).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between rounded border border-ink-800 px-2 py-1 font-mono text-xs"><span>{k}: <span className="text-ink-400">{v}</span></span>
                <button className="text-observed" onClick={() => { const next = { ...s.custom_patterns }; delete next[k]; set("custom_patterns", next); }}>remove</button></li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input className="input" placeholder="name" value={patternName} onChange={(e) => setPatternName(e.target.value)} aria-label="Pattern name" />
            <input className="input font-mono" placeholder="regex e.g. EMP-\d{6}" value={patternRegex} onChange={(e) => setPatternRegex(e.target.value)} aria-label="Pattern regex" />
            <button className="btn-ghost" onClick={() => { if (patternName && patternRegex) { set("custom_patterns", { ...s.custom_patterns, [patternName]: patternRegex }); setPatternName(""); setPatternRegex(""); } }}><Plus className="h-4 w-4" /></button>
          </div>
          <p className="mt-2 text-[11px] text-ink-500">Remember to Save settings after editing rules.</p>
          <div className="label mt-4">Test redaction (nothing is stored)</div>
          <textarea className="input font-mono text-xs" rows={2} value={previewText} onChange={(e) => setPreviewText(e.target.value)} aria-label="Redaction test text" />
          <button className="btn-ghost mt-2" onClick={() => guarded(async () => setPreview(await api.redactionPreview(previewText)), "Preview generated with saved rules")}>Preview redaction</button>
          {preview && <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-ink-800 bg-ink-950 p-2 font-mono text-xs text-ink-200" data-testid="redaction-preview">{preview.redacted}</pre>}
        </Card>
        <Card title="Evaluation categories">
          <div className="mb-3 flex flex-wrap gap-1.5">
            {cats.data?.map((c) => <Badge key={c.name} tone={c.is_builtin ? "pending" : "candidate"}>{c.name}</Badge>)}
          </div>
          <div className="flex gap-2">
            <input className="input font-mono" placeholder="new_category" value={newCat} onChange={(e) => setNewCat(e.target.value)} aria-label="New category name" />
            <input className="input" placeholder="description" value={newCatDesc} onChange={(e) => setNewCatDesc(e.target.value)} aria-label="New category description" />
            <button className="btn-ghost" onClick={() => guarded(async () => { await api.createCategory(newCat, newCatDesc); setNewCat(""); setNewCatDesc(""); cats.reload(); }, "Category added")}>Add</button>
          </div>
          <p className="mt-2 text-[11px] text-ink-500">lowercase letters, digits and underscores.</p>
          <div className="mt-6 border-t border-ink-800 pt-4">
            <div className="label text-observed">Danger zone</div>
            <button className="btn border border-observed/40 text-observed hover:bg-observed/10" onClick={() => { if (window.confirm("Delete ALL ingested logs, traces and datasets?")) void guarded(() => api.reset(adminKey), "All data deleted"); }}>Reset all data</button>
          </div>
        </Card>
      </div>
    </div>
  );
}
