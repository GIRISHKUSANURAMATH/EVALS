import type { QualityFactor } from "../api/types";

export default function QualityFactors({ factors, score }: { factors: QualityFactor[]; score: number }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="label mb-0">Quality score</span>
        <span className="font-mono text-lg text-accent" data-testid="quality-score">{score.toFixed(2)}</span>
      </div>
      <ul className="space-y-1.5">
        {factors.map((f) => (
          <li key={f.name} title={f.explanation}>
            <div className="flex justify-between text-[11px]">
              <span className="font-mono text-ink-300">{f.name.replace(/_/g, " ")}</span>
              <span className="font-mono text-ink-500">
                {f.value.toFixed(2)} × {f.weight}
              </span>
            </div>
            <div className="mt-0.5 h-1 rounded bg-ink-800">
              <div className={`h-1 rounded ${f.value >= 0.8 ? "bg-ok" : f.value >= 0.5 ? "bg-heuristic" : "bg-observed"}`} style={{ width: `${f.value * 100}%` }} />
            </div>
            <div className="text-[11px] text-ink-500">{f.explanation}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
