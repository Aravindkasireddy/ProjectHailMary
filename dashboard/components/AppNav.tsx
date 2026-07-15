'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Briefcase,
  BarChart3,
  Settings,
  Shield,
  Globe,
  KanbanSquare,
  FileText,
  LogOut,
  BellRing,
  ChevronRight,
} from 'lucide-react';

interface AppNavProps {
  authRole: 'admin' | 'user' | null;
  authEmail: string | null;
  activeTab: string;
  onTabChange: (tab: string) => void;  // accepts TabId; typed as string to avoid import cycle
  onLogout: () => void;
  webhookActive: boolean;
  webhookSource?: string;
}

const NAV_ITEMS = [
  { id: 'approved',     label: 'Job Feed',        icon: Briefcase,    roles: ['admin', 'user'] },
  { id: 'new_today',    label: 'New Today',        icon: BellRing,     roles: ['admin', 'user'] },
  { id: 'applications', label: 'Applications',     icon: KanbanSquare, roles: ['admin', 'user'] },
  { id: 'analytics',   label: 'Analytics',        icon: BarChart3,    roles: ['admin', 'user'] },
  { id: 'resume',      label: 'Resume',           icon: FileText,     roles: ['admin'] },
  { id: 'policy',      label: 'Policy',           icon: Shield,       roles: ['admin'] },
  { id: 'settings',    label: 'Settings',         icon: Settings,     roles: ['admin'] },
] as const;

export default function AppNav({
  authRole,
  authEmail,
  activeTab,
  onTabChange,
  onLogout,
  webhookActive,
  webhookSource,
}: AppNavProps) {
  const pathname = usePathname();
  const onDashboard = pathname === '/';

  return (
    <aside className="w-56 shrink-0 bg-slate-950 border-r border-slate-800/80 flex flex-col h-screen sticky top-0 z-30">

      {/* Brand */}
      <div className="px-4 py-5 border-b border-slate-800/60">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-lg shadow-lg shadow-violet-500/20 shrink-0">
            <Briefcase className="w-4 h-4 text-white" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-white truncate leading-tight">MAAS Agent</p>
            <p className="text-[10px] text-slate-500 truncate">Sourcing Dashboard</p>
          </div>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
        {NAV_ITEMS.filter(item => authRole && (item.roles as readonly string[]).includes(authRole)).map(item => {
          const Icon = item.icon;
          const active = onDashboard && activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left ${
                active
                  ? 'bg-violet-600/20 text-violet-300 border border-violet-600/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <Icon className={`w-4 h-4 shrink-0 ${active ? 'text-violet-400' : ''}`} />
              {item.label}
            </button>
          );
        })}

        <div className="pt-2 border-t border-slate-800/60 mt-2">
          <Link
            href="/company-scraper"
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition-colors"
          >
            <Globe className="w-4 h-4 shrink-0" />
            Company Scraper
            <ChevronRight className="w-3.5 h-3.5 ml-auto opacity-50" />
          </Link>
        </div>
      </nav>

      {/* Footer — user info + logout */}
      <div className="px-3 py-3 border-t border-slate-800/60 space-y-2">
        {webhookActive && (
          <div className="flex items-center gap-1.5 text-[10px] text-indigo-400 px-1">
            <BellRing className="w-3 h-3 shrink-0" />
            <span>Discord{webhookSource === 'environment' ? ' (env)' : ''}</span>
          </div>
        )}
        <div className="flex items-center gap-2 px-1">
          <div className={`w-2 h-2 rounded-full shrink-0 ${authRole === 'admin' ? 'bg-violet-400' : 'bg-slate-500'}`} />
          <span className="text-[11px] text-slate-400 truncate flex-1">
            {authEmail || (authRole === 'admin' ? 'Admin' : 'User')}
          </span>
          <button
            onClick={onLogout}
            title="Log out"
            className="p-1 text-slate-500 hover:text-rose-400 transition-colors rounded"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
