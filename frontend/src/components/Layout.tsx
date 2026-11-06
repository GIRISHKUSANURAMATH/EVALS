import {
  Boxes,
  ClipboardCheck,
  Database,
  Download,
  GitBranch,
  LayoutDashboard,
  ListTree,
  Settings,
  ShieldAlert,
  Upload,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload Logs", icon: Upload },
  { to: "/pipeline", label: "Processing Pipeline", icon: GitBranch },
  { to: "/traces", label: "Traces Explorer", icon: ListTree },
  { to: "/failures", label: "Failure Analysis", icon: ShieldAlert },
  { to: "/clusters", label: "Semantic Clusters", icon: Boxes },
  { to: "/datasets", label: "Generated Datasets", icon: Database },
  { to: "/review", label: "Human Review", icon: ClipboardCheck },
  { to: "/export", label: "Export Center", icon: Download },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout() {
  const health = useAsync(() => api.health(), []);
  const online = health.data?.status === "ok";
  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-ink-800 bg-ink-900/60 px-3 py-5 md:flex">
        <div className="mb-8 flex items-center gap-2 px-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent-dim ring-1 ring-accent/40">
            <span className="font-mono text-sm font-bold text-accent">ev</span>
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide">EVALS</div>
            <div className="text-[10px] uppercase tracking-widest text-ink-500">logs → eval datasets</div>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5" aria-label="Main navigation">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                  isActive ? "bg-ink-800 text-ink-100 ring-1 ring-ink-700" : "text-ink-400 hover:bg-ink-850 hover:text-ink-200"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-4 rounded-lg border border-ink-800 p-3 text-xs text-ink-400">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${online ? "bg-ok" : health.loading ? "bg-ink-500" : "bg-observed"}`} />
            {online ? "Backend online" : health.loading ? "Connecting…" : "Backend offline"}
          </div>
          {health.data && <div className="mt-1 font-mono text-ink-500">v{health.data.version}</div>}
          <a className="mt-2 block text-accent hover:underline" href="/docs" target="_blank" rel="noreferrer">
            API docs ↗
          </a>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 overflow-x-auto border-b border-ink-800 px-4 py-2 md:hidden">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `whitespace-nowrap rounded-md px-2 py-1 text-xs ${isActive ? "bg-ink-800 text-ink-100" : "text-ink-400"}`}>
              {label}
            </NavLink>
          ))}
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
