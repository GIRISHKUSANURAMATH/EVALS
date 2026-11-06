import { Download, Eye } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Card, EmptyState, ErrorBanner, PageHeader, Select, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export default function ExportPage() {
  const [params] = useSearchParams();
  const datasets = useAsync(() => api.datasets(), []);
  const cats = useAsync(() => api.categories(), []);
  const [datasetId, setDatasetId] = useState(params.get("dataset") ?? "");
  const [format, setFormat] = useState("jsonl");
  const [scope, setScope] = useState("approved");
  const [selectedCats, setSelectedCats] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [preview, setPreview] = useState<{ text: string; count: number }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (datasets.loading && !datasets.data) return <Spinner />;
  if (datasets.error) return <ErrorBanner message={datasets.error} />;
  const items = datasets.data?.items ?? [];
  if (!items.length) return (<div><PageHeader title="Export Center" /><EmptyState title="Nothing to export yet" body="Generate a dataset first." /></div>);
  const active = datasetId || items[0].id;

  const url = api.exportUrl(active, {
    format,
    approved_only: scope === "approved",
    categories: selectedCats.join(",") || undefined,
    date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
    date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
  });

  async function doPreview() {
    setBusy(true);
    setError(undefined);
    try {
      setPreview(await api.exportPreview(url));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Export Center" subtitle="Exports are validated against a schema and re-scanned for secrets before download. Records include an OpenAI-style messages array." />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Export options" className="lg:col-span-2">
          <div className="space-y-3">
            <Select label="Dataset" value={active} onChange={(v) => { setDatasetId(v); setPreview(undefined); }} options={items.map((d) => ({ value: d.id, label: `${d.name} (${d.approved_count}/${d.example_count} approved)` }))} />
            <div>
              <span className="label">Format</span>
              <div className="flex gap-1" role="radiogroup" aria-label="Format">
                {["jsonl", "csv", "json"].map((f) => (
                  <button key={f} role="radio" aria-checked={format === f} onClick={() => { setFormat(f); setPreview(undefined); }} className={`flex-1 rounded-lg py-1.5 font-mono text-xs ring-1 ${format === f ? "bg-accent/15 text-accent ring-accent/40" : "text-ink-400 ring-ink-700"}`}>
                    .{f}
                  </button>
                ))}
              </div>
            </div>
            <Select label="Examples" value={scope} onChange={(v) => { setScope(v); setPreview(undefined); }} options={[{ value: "approved", label: "Approved only" }, { value: "all", label: "All generated examples" }]} />
            <div className="grid grid-cols-2 gap-2">
              <label className="block"><span className="label">From</span><input type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} aria-label="Date from" /></label>
              <label className="block"><span className="label">To</span><input type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="Date to" /></label>
            </div>
            <div>
              <span className="label">Categories (none = all)</span>
              <div className="flex flex-wrap gap-1.5">
                {cats.data?.map((c) => (
                  <button key={c.name} onClick={() => setSelectedCats((s) => (s.includes(c.name) ? s.filter((x) => x !== c.name) : [...s, c.name]))} className={`rounded-md px-2 py-1 font-mono text-[11px] ring-1 ${selectedCats.includes(c.name) ? "bg-accent/15 text-accent ring-accent/40" : "text-ink-400 ring-ink-700"}`}>
                    {c.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <button className="btn-ghost" onClick={doPreview} disabled={busy}><Eye className="h-4 w-4" /> Preview</button>
              <a className="btn-primary" href={url} download data-testid="download-link"><Download className="h-4 w-4" /> Download</a>
            </div>
            {error && <ErrorBanner message={error} />}
          </div>
        </Card>
        <Card title="Preview" className="lg:col-span-3" actions={preview && <span className="font-mono text-xs text-ink-400">{preview.count} examples</span>}>
          {preview ? (
            preview.count === 0 ? <EmptyState title="No examples match these filters" body={scope === "approved" ? "Approve examples in Human Review first, or export all examples." : undefined} /> : (
              <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-all rounded-lg border border-ink-800 bg-ink-950 p-3 font-mono text-[11px] text-ink-300" data-testid="export-preview">
                {preview.text.slice(0, 20000)}{preview.text.length > 20000 && "\n… (truncated preview)"}
              </pre>
            )
          ) : <div className="text-sm text-ink-500">Click Preview to inspect the exact file contents before downloading.</div>}
        </Card>
      </div>
    </div>
  );
}
