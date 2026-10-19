import clsx from 'clsx';
import { FileText, FlaskConical, LayoutDashboard, Menu, MessageSquare, Moon, Settings, Sun, X } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet } from 'react-router';
import { useHealth, useTheme } from '../../hooks/useSystem';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/chat', label: 'Chat', icon: MessageSquare, end: false },
  { to: '/documents', label: 'Documents', icon: FileText, end: false },
  { to: '/evaluations', label: 'Evaluations', icon: FlaskConical, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
];

function HealthDot() {
  const { data, isError } = useHealth();
  const state = isError ? 'down' : (data?.status ?? 'unknown');
  const color = state === 'ok' ? 'bg-emerald-500' : state === 'degraded' ? 'bg-amber-500' : state === 'down' ? 'bg-red-500' : 'bg-slate-400';
  const label = state === 'ok' ? 'Backend healthy' : state === 'degraded' ? 'Backend degraded' : state === 'down' ? 'Backend unreachable' : 'Checking backend…';
  return (
    <span className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400" title={label}>
      <span className={clsx('h-2 w-2 rounded-full', color)} aria-hidden />
      {label}
    </span>
  );
}

export function AppLayout() {
  const [open, setOpen] = useState(false);
  const { theme, toggle } = useTheme();

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-500'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100',
            )
          }
        >
          <Icon className="h-4 w-4" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-5 lg:flex dark:border-slate-800 dark:bg-slate-900">
        <Brand />
        <div className="mt-8 flex-1">{nav}</div>
        <HealthDot />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-950/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white px-4 py-5 dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <Brand />
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-8 flex-1">{nav}</div>
            <HealthDot />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur lg:px-8 dark:border-slate-800 dark:bg-slate-950/80">
          <button aria-label="Open navigation" onClick={() => setOpen(true)} className="rounded p-1 hover:bg-slate-100 lg:hidden dark:hover:bg-slate-800">
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden">
            <Brand compact />
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              onClick={toggle}
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">R</div>
      {!compact && (
        <div className="leading-tight">
          <p className="text-sm font-semibold">RAG Platform</p>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">Document intelligence</p>
        </div>
      )}
    </div>
  );
}
