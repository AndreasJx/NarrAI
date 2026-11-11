"use client";

import {
  BarChart3,
  BookOpen,
  Bot,
  CalendarDays,
  CirclePlay,
  LayoutDashboard,
  LogOut,
  Menu,
  Mic2,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { initials, money, ROLE_LABEL } from "@/lib/format";
import { useResource } from "@/lib/hooks";

import { NewVideoModal } from "./NewVideoModal";
import { useSession } from "./Session";
import { useToast } from "./Toast";

const NAV = [
  { href: "/", label: "Visão geral", icon: LayoutDashboard },
  { href: "/projects", label: "Projetos", icon: CirclePlay, count: true },
  { href: "/autopilot", label: "Piloto automático", icon: Bot },
  { href: "/calendar", label: "Calendário", icon: CalendarDays },
  { href: "/performance", label: "Desempenho", icon: BarChart3 },
];
const ShellActions = createContext<() => void>(() => undefined);

const LIBRARY = [
  { href: "/sources", label: "Fontes", icon: BookOpen },
  { href: "/voice", label: "Voz e avatar", icon: Mic2 },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { me, logout, replace } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [userMenu, setUserMenu] = useState(false);
  const dashboard = useResource(api.dashboard, `shell:${me.organization.id}:${pathname}`);
  const openComposer = useCallback(() => setComposerOpen(true), []);

  const spent = dashboard.data?.spent_cents ?? 0;
  const budget = dashboard.data?.monthly_budget_cents ?? me.organization.monthly_budget_cents;
  const usage = budget ? Math.min(100, Math.round((spent / budget) * 100)) : 0;
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  async function switchOrganization(id: number) {
    try {
      replace(await api.auth.switchOrganization(id));
      setUserMenu(false);
      router.push("/");
    } catch (error) {
      toast.error(error);
    }
  }

  const link = (item: (typeof NAV)[number] | (typeof LIBRARY)[number]) => {
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        className={`nav-item ${isActive(item.href) ? "active" : ""}`}
        href={item.href}
        onClick={() => setMenuOpen(false)}
      >
        <Icon size={19} />
        {item.label}
        {"count" in item && item.count && dashboard.data && <span className="nav-count">{dashboard.data.project_count}</span>}
      </Link>
    );
  };

  return (
    <ShellActions.Provider value={openComposer}>
    <main className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark"><Sparkles size={19} /></span>
          <span>Narra</span>
          <button className="mobile-close" onClick={() => setMenuOpen(false)} aria-label="Fechar menu"><X /></button>
        </div>
        <nav className="nav-list" aria-label="Navegação principal">
          {NAV.map(link)}
          <div className="nav-label">Biblioteca</div>
          {LIBRARY.map(link)}
        </nav>
        <div className="sidebar-foot">
          <div className="budget">
            <div><span>Uso mensal</span><strong>{money(spent)}</strong></div>
            <div className="progress"><i style={{ width: `${usage}%` }} /></div>
            <small>de {money(budget)}</small>
          </div>
          {link({ href: "/settings", label: "Configurações", icon: Settings })}
          <div className="profile">
            <span>{initials(me.user.name)}</span>
            <div><strong>{me.user.name}</strong><small>{ROLE_LABEL[me.role]} · {me.organization.name}</small></div>
          </div>
        </div>
      </aside>
      {menuOpen && <div className="sidebar-scrim" onClick={() => setMenuOpen(false)} />}

      <section className="workspace">
        <header className="topbar">
          <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Abrir menu"><Menu /></button>
          <div className="mobile-wordmark">Narra</div>
          <div className="top-actions">
            <div className="platform-status">
              <i className={dashboard.data?.connected_channels ? "" : "off"} />
              <span>
                {dashboard.data?.connected_channels
                  ? `${dashboard.data.connected_channels} ${dashboard.data.connected_channels === 1 ? "canal conectado" : "canais conectados"}`
                  : "Nenhum canal conectado"}
              </span>
            </div>
            <div className="user-menu">
              <button className="avatar-button" onClick={() => setUserMenu((open) => !open)} aria-label="Menu do usuário">
                {initials(me.user.name)}
              </button>
              {userMenu && (
                <div className="dropdown" onMouseLeave={() => setUserMenu(false)}>
                  <div className="dropdown-head">
                    <strong>{me.user.name}</strong>
                    <small>{me.user.email}</small>
                  </div>
                  {me.organizations.length > 1 && (
                    <>
                      <div className="dropdown-label">Organizações</div>
                      {me.organizations.map((organization) => (
                        <button
                          key={organization.id}
                          className={organization.id === me.organization.id ? "current" : ""}
                          onClick={() => switchOrganization(organization.id)}
                        >
                          {organization.name}
                        </button>
                      ))}
                    </>
                  )}
                  <Link href="/settings" onClick={() => setUserMenu(false)}><Settings size={15} />Configurações</Link>
                  <button onClick={logout}><LogOut size={15} />Sair</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <div className="content">{children}</div>
      </section>

      {composerOpen && <NewVideoModal onClose={() => setComposerOpen(false)} />}
    </main>
    </ShellActions.Provider>
  );
}

export const useOpenComposer = () => useContext(ShellActions);
