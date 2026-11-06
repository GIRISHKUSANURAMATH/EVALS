import { Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, fmt } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export default function DatasetsPage() {
  const list = useAsync(() => api.datasets(), []);
  const cats = useAsync(() => api.categories(), []);
  const navigate = useNavigate();
  const [name, setName] = useState(`eval-set-${new Date().toISOString().slice(0, 10)}`);
  const [description, setDescription] = useState("");
  const [includeSuccess, setIncludeSuccess] = useState(true);
  const [excludeDup, setExcludeDup] = useState(true);
  const [minQuality, setMinQuality] = useState(0);
  const [maxExamples, setMaxExamples] = useState(5000);
  const [selectedCats, setSelectedCats] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const ds = await api.generate({
        name,
        description,
        include_successful: includeSuccess,
        exclude_duplicates: excludeDup,
        categories: selectedCats.length ? selectedCats : null,
        min_quality: minQuality,
        max_examples: maxExamples,
      });
      navigate(`/datasets/${ds.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggle(c: string) {
    setSelectedCats((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]));
  }

  return (
    <div>
      <PageHeader title="Generated Datasets" subtitle="Generate versioned evaluation datasets from processed traces." />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Generate a new dataset" className="lg:col-span-2">
          <form onSubmit={submit} className="space-y-3">
            <label className="block"><span className="label">Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} /></label>
            <label className="block"><span className="label">Description</span><textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block"><span className="label">Min quality</span><input className="input" type="number" step={0.05} min={0} max={1} value={minQuality} onChange={(e) => setMinQuality(Number(e.target.value))} /></label>
              <label className="block"><span className="label">Max examples</span><input className="input" type="number" min={1} max={100000} value={maxExamples} onChange={(e) => setMaxExamples(Number(e.target.value))} /></label>
            </div>
            <label className="flex items-center gap-2 text-sm text-ink-300"><input type="checkbox" checked={includeSuccess} onChange={(e) => setIncludeSuccess(e.target.checked)} /> Include successful interactions (regression baseline)</label>
            <label className="flex items-center gap-2 text-sm text-ink-300"><input type="checkbox" checked={excludeDup} onChange={(e) => setExcludeDup(e.target.checked)} /> Exclude duplicates</label>
            <div>
              <span className="label">Categories (none selected = all)</span>
              <div className="flex flex-wrap gap-1.5">
                {cats.data?.map((c) => (
                  <button type="button" key={c.name} onClick={() => toggle(c.name)} title={c.description} className={`rounded-md px-2 py-1 font-mono text-[11px] ring-1 ${selectedCats.includes(c.name) ? "bg-accent/15 text-accent ring-accent/40" : "text-ink-400 ring-ink-700 hover:text-ink-200"}`}>
                    {c.name}
                  </button>
                ))}
              </div>
            </div>
            {error && <ErrorBanner message={error} />}
            <button type="submit" className="btn-primary w-full justify-center" disabled={busy}>
              <Sparkles className="h-4 w-4" /> {busy ? "Generating…" : "Generate dataset"}
            </button>
          </form>
        </Card>
        <Card title="Datasets" className="lg:col-span-3">
          {list.loading && !list.data ? <Spinner /> : list.error ? <ErrorBanner message={list.error} /> : list.data!.items.length === 0 ? (
            <EmptyState title="No datasets yet" body="Generate one from the form. You need processed logs first." />
          ) : (
            <ul className="divide-y divide-ink-800">
              {list.data!.items.map((d) => {
                const pct = d.example_count ? ((d.approved_count ?? 0) / d.example_count) * 100 : 0;
                return (
                  <li key={d.id} className="py-3">
                    <div className="flex items-center justify-between gap-3">
                      <Link to={`/datasets/${d.id}`} className="font-medium text-ink-100 hover:text-accent">{d.name}</Link>
                      <Badge tone="pending">{`v${d.current_version}`}</Badge>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-ink-400">
                      <span>{fmt.int(d.example_count)} examples</span>
                      <span>{fmt.int(d.approved_count)} approved</span>
                      <span>{fmt.date(d.created_at)}</span>
                    </div>
                    <div className="mt-2 h-1 rounded bg-ink-800"><div className="h-1 rounded bg-ok" style={{ width: `${pct}%` }} /></div>
                    <div className="mt-2 flex gap-3 text-xs">
                      <Link className="text-accent hover:underline" to={`/review?dataset=${d.id}`}>Review</Link>
                      <Link className="text-accent hover:underline" to={`/export?dataset=${d.id}`}>Export</Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
