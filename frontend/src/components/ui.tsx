import { AlertTriangle, ChevronLeft, ChevronRight, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink-100">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, children, className = "", actions }: { title?: string; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <section className={`card animate-rise p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-ink-200">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone = "default", icon }: { label: string; value: ReactNode; hint?: string; tone?: "default" | "accent" | "bad" | "warn"; icon?: ReactNode }) {
  const toneCls = { default: "text-ink-100", accent: "text-accent", bad: "text-observed", warn: "text-heuristic" }[tone];
  return (
    <div className="card animate-rise p-4" data-testid={`stat-${label}`}>
      <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-ink-400">
        <span>{label}</span>
        <span className="text-ink-500">{icon}</span>
      </div>
      <div className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${toneCls}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-500">{hint}</div>}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  ok: "bg-ok/10 text-ok ring-ok/30",
  completed: "bg-ok/10 text-ok ring-ok/30",
  approved: "bg-ok/10 text-ok ring-ok/30",
  human_approved: "bg-ok/10 text-ok ring-ok/30",
  failed: "bg-observed/10 text-observed ring-observed/30",
  rejected: "bg-observed/10 text-observed ring-observed/30",
  observed: "bg-observed/10 text-observed ring-observed/30",
  high: "bg-observed/10 text-observed ring-observed/30",
  warning: "bg-heuristic/10 text-heuristic ring-heuristic/30",
  heuristic: "bg-heuristic/10 text-heuristic ring-heuristic/30",
  flagged: "bg-heuristic/10 text-heuristic ring-heuristic/30",
  medium: "bg-heuristic/10 text-heuristic ring-heuristic/30",
  candidate: "bg-info/10 text-info ring-info/30",
  processing: "bg-info/10 text-info ring-info/30",
  pending: "bg-ink-700/60 text-ink-300 ring-ink-600",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const key = tone ?? (typeof children === "string" ? children : "");
  const cls = BADGE_TONES[key] ?? "bg-ink-800 text-ink-300 ring-ink-600";
  return <span className={`inline-flex items-center whitespace-nowrap rounded-md px-1.5 py-0.5 font-mono text-[11px] ring-1 ring-inset ${cls}`}>{children}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-ink-400" role="status">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}…
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-observed/30 bg-observed/5 p-3 text-sm text-observed">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1">{message}</div>
      {onRetry && (
        <button className="btn-ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-ink-700 p-10 text-center">
      <Inbox className="h-8 w-8 text-ink-500" />
      <div className="text-sm font-medium text-ink-200">{title}</div>
      {body && <p className="max-w-md text-sm text-ink-400">{body}</p>}
      {action}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between pt-3 text-xs text-ink-400">
      <span>
        {total === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button className="btn-ghost px-2" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="px-2 font-mono">
          {page}/{pages}
        </span>
        <button className="btn-ghost px-2" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-xs text-ink-300 ${className}`}>{children}</span>;
}

export function TextBlock({ label, text, tone }: { label: string; text: string | null | undefined; tone?: string }) {
  return (
    <div>
      <div className="label flex items-center gap-2">
        {label} {tone && <Badge tone={tone}>{tone}</Badge>}
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink-700 bg-ink-950 p-3 font-mono text-xs leading-relaxed text-ink-200">
        {text === null || text === undefined ? <span className="italic text-ink-500">(none)</span> : text === "" ? <span className="italic text-ink-500">(empty string)</span> : text}
      </pre>
    </div>
  );
}

export function Select({ value, onChange, options, label, ariaLabel }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label?: string; ariaLabel?: string }) {
  return (
    <label className="block">
      {label && <span className="label">{label}</span>}
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel ?? label}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export const fmt = {
  int: (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toLocaleString()),
  ms: (n: number | null | undefined) => (n === null || n === undefined ? "—" : n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`),
  pct: (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${n.toFixed(1)}%`),
  date: (s: string | null | undefined) => (s ? new Date(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`).toLocaleString() : "—"),
  bytes: (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024).toFixed(1)} KB`),
  score: (n: number) => n.toFixed(2),
};

export function truncate(s: string | null | undefined, n = 120): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n)}…` : s;
}
