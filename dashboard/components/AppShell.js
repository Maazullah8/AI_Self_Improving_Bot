"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  FlaskConical,
  GitBranch,
  History,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
} from "lucide-react";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, match: "exact" },
  { href: "/live-trades", label: "Live Trades", icon: Activity },
  { href: "/trade-history", label: "Trade History", icon: History },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/backtesting", label: "Backtesting", icon: FlaskConical },
  { href: "/trade-journal", label: "Trade Journal", icon: BookOpen },
  { href: "/ai-learning", label: "AI Learning", icon: Sparkles, aiGlow: true },
  { href: "/strategy-versions", label: "Strategy Versions", icon: GitBranch },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];

const TITLES = {
  "/": "Dashboard",
  "/live-trades": "Live Trades",
  "/trade-history": "Trade History",
  "/analytics": "Analytics",
  "/backtesting": "Backtesting",
  "/trade-journal": "Trade Journal",
  "/ai-learning": "AI Learning",
  "/strategy-versions": "Strategy Versions",
  "/alerts": "Alerts",
  "/settings": "Settings",
};

function useClock() {
  const [now, setNow] = useState("");
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setNow(
        `${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · ${d.toLocaleTimeString(undefined, { hour12: false })} UTC`,
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function AppShell({ children }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [online, setOnline] = useState(true);
  const clock = useClock();

  useEffect(() => {
    let alive = true;
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setOnline(d.status === "ok"))
      .catch(() => alive && setOnline(false));
    const id = setInterval(() => {
      fetch("/api/health")
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => alive && setOnline(d.status === "ok"))
        .catch(() => alive && setOnline(false));
    }, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const title = TITLES[pathname] ?? "Dashboard";

  return (
    <div className="flex h-screen overflow-hidden">
      <aside
        className={`fixed left-0 top-0 h-full z-40 flex flex-col bg-sidebar border-r border-border overflow-hidden shrink-0 transition-all duration-200 ${
          collapsed ? "w-[60px]" : "w-[220px]"
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 h-16 border-b border-border shrink-0 min-w-0">
          <div className="size-7 rounded-lg bg-ai flex items-center justify-center shrink-0 glow-ai">
            <Sparkles className="size-4 text-white" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-sm font-bold text-foreground truncate leading-tight">AI ImprovBot</div>
              <div className="text-[10px] text-muted-foreground truncate">Trading Intelligence</div>
            </div>
          )}
        </div>

        <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
          {NAV.map((item) => {
            const active =
              item.match === "exact" ? pathname === item.href : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-2.5 py-2 rounded-md text-xs font-medium transition-all duration-150 group relative ${
                  active
                    ? "bg-ai/15 text-ai"
                    : "text-muted-foreground hover:text-foreground hover:bg-white/5"
                } ${collapsed ? "justify-center px-0" : ""}`}
              >
                <Icon
                  className={`size-4 shrink-0 transition-colors ${active ? "text-ai" : item.aiGlow ? "text-ai" : "text-muted-foreground group-hover:text-foreground/80"}`}
                />
                {!collapsed && <span className="truncate flex-1">{item.label}</span>}
                {!collapsed && item.badge && (
                  <span className="text-[10px] px-1.5 py-0 h-4 bg-ai/20 text-ai border border-ai/20 rounded-md inline-flex items-center shrink-0">
                    {item.badge}
                  </span>
                )}
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full bg-ai" />
                )}
              </Link>
            );
          })}
        </nav>

        <div className="px-2 py-3 border-t border-border shrink-0">
          <div className={`flex items-center gap-2 px-2.5 py-2 rounded-md bg-profit/10 border border-profit/20 ${collapsed ? "justify-center" : ""}`}>
            <div className="size-2 rounded-full bg-profit animate-pulse-slow shrink-0" />
            {!collapsed && (
              <span className="text-[11px] font-medium text-profit truncate">
                {online ? "System Online" : "Backend Offline"}
              </span>
            )}
          </div>
        </div>

        <button
          onClick={() => setCollapsed((c) => !c)}
          className="absolute -right-3 top-16 size-6 rounded-full bg-sidebar border border-border flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors z-50 shadow-md"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen className="size-3" /> : <PanelLeftClose className="size-3" />}
        </button>
      </aside>

      <div className={`flex-1 flex flex-col min-w-0 transition-all duration-200 ${collapsed ? "ml-[60px]" : "ml-[220px]"}`}>
        <header className="h-16 shrink-0 border-b border-border bg-background/80 backdrop-blur flex items-center justify-between px-6">
          <div className="flex items-baseline gap-2">
            <h1 className="text-lg font-bold tracking-tight">{title}</h1>
            <span className="text-xs text-muted-foreground hidden sm:inline">Trading Intelligence Platform</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground font-mono hidden md:inline">{clock}</span>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-profit">
              <span className="size-2 rounded-full bg-profit animate-pulse-slow" />
              {online ? "System Online" : "Offline"}
            </span>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] p-6 space-y-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
