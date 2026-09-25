'use client';

import type { ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  BarChart3,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Menu,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { OpportunityNotifications } from '@/components/platform/opportunity-notifications';

const navigation = [
  { href: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { href: '/configuracoes', label: 'Configurações', icon: SlidersHorizontal },
];

export function AppShell({
  children,
  user,
  onSignOut,
}: {
  children: ReactNode;
  user: { name: string; email: string };
  onSignOut: () => void;
}) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const menu = (
    <>
      <div className={`flex h-20 items-center gap-3 border-b border-white/10 ${collapsed ? 'lg:justify-center lg:px-2' : 'px-5'}`}>
        <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-600 text-sm font-black tracking-tight text-white ring-1 ring-white/20">
          CX
        </div>
        <div className={`min-w-0 ${collapsed ? 'lg:hidden' : ''}`}>
          <p className="text-sm font-bold tracking-tight text-white">PDOH_CX</p>
          <p className="text-[11px] text-blue-200/70">Painel operacional</p>
        </div>
      </div>
      <nav
        className={`flex-1 space-y-1 py-5 ${collapsed ? 'lg:px-2' : 'px-3'}`}
        aria-label="Navegação principal"
      >
        <p className={`mb-3 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-blue-200/45 ${collapsed ? 'lg:sr-only' : ''}`}>
          Navegação
        </p>
        <button type="button" onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? 'Expandir sidebar' : 'Recolher sidebar'} title={collapsed ? 'Expandir sidebar' : 'Recolher sidebar'}
          className={`mb-4 hidden min-h-10 w-full items-center gap-3 rounded-lg px-3 text-blue-200/70 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-white lg:flex ${collapsed ? 'justify-center' : ''}`}>
          {collapsed ? <PanelLeftOpen className="size-5 shrink-0" /> : <PanelLeftClose className="size-5 shrink-0" />}
          {!collapsed && <span className="text-xs font-semibold">Recolher</span>}
        </button>
        {navigation.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href === '/dashboard' && pathname.startsWith('/marcas/')) ||
            (href !== '/dashboard' && pathname.startsWith(`${href}/`));
          return (
            <NavLink
              key={href}
              to={href}
              onClick={() => setOpen(false)}
              title={collapsed ? label : undefined}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'group relative flex min-h-11 items-center gap-3 rounded-lg border px-3 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-white',
                collapsed && 'lg:justify-center',
                active
                  ? 'border-blue-400/30 bg-blue-600 text-white shadow-sm'
                  : 'border-transparent text-blue-100/75 hover:border-white/10 hover:bg-white/[.08] hover:text-white',
              )}
            >
              <Icon
                className={cn(
                  'size-5 shrink-0',
                  active
                    ? 'text-white'
                    : 'text-blue-300/70 group-hover:text-blue-300',
                )}
                aria-hidden="true"
              />
              <span className={collapsed ? 'lg:sr-only' : ''}>{label}</span>
              {collapsed && <span role="tooltip" className="pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 lg:block">
                {label}
              </span>}
            </NavLink>
          );
        })}
      </nav>
      <div className={`border-t border-white/10 ${collapsed ? 'lg:p-2' : 'p-3'}`}>
        <div className={`mb-1 flex items-center gap-3 rounded-xl p-2 ${collapsed ? 'lg:justify-center' : ''}`}>
          <div className="grid size-9 place-items-center rounded-full bg-blue-400/20 text-xs font-bold text-blue-100">
            {user.name.slice(0, 2).toUpperCase()}
          </div>
          <div className={`min-w-0 flex-1 ${collapsed ? 'lg:hidden' : ''}`}>
            <p className="truncate text-sm font-medium text-white">
              {user.name}
            </p>
            <p className="truncate text-xs text-blue-200/60">{user.email}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onSignOut}
          title={collapsed ? 'Encerrar sessão' : undefined}
          className={`flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-xs text-blue-200/70 transition-colors hover:bg-white/10 hover:text-white ${collapsed ? 'lg:justify-center' : ''}`}
        >
          <LogOut className="size-4 shrink-0" aria-hidden="true" />
          <span className={collapsed ? 'lg:sr-only' : ''}>Encerrar sessão</span>
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-[#f4f7fb]">
      <aside className={`fixed inset-y-0 left-0 z-40 hidden flex-col overflow-visible bg-[linear-gradient(180deg,#07152f_0%,#0a1e43_60%,#07152f_100%)] shadow-xl transition-[width] duration-200 motion-reduce:transition-none lg:flex ${collapsed ? 'w-20' : 'w-64'}`}>
        {menu}
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            className="absolute inset-0 bg-slate-950/60"
            aria-label="Fechar menu"
            onClick={() => setOpen(false)}
          />
          <aside className="relative flex h-full w-72 flex-col bg-slate-950">
            {menu}
            <Button
              variant="ghost"
              size="icon"
              aria-label="Fechar navegação"
              className="absolute right-3 top-3 text-white"
              onClick={() => setOpen(false)}
            >
              <X />
            </Button>
          </aside>
        </div>
      )}
      <div className={`min-w-0 overflow-x-hidden transition-[padding] duration-200 motion-reduce:transition-none ${collapsed ? 'lg:pl-20' : 'lg:pl-64'}`}>
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-4 backdrop-blur md:px-6">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Abrir navegação"
            className="lg:hidden"
            onClick={() => setOpen(true)}
          >
            <Menu />
          </Button>
          <div className="hidden sm:block">
            <p className="text-[10px] font-bold uppercase tracking-[.15em] text-slate-400">
              CX Intelligence Workspace
            </p>
            <p className="text-sm font-semibold text-slate-800">
              Consulta operacional PDOH_CX
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <OpportunityNotifications key={user.email} userId={user.email} />
          </div>
        </header>
        <main className="mx-auto min-w-0 max-w-[1540px] p-3 pb-24 md:p-5 xl:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
