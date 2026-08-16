"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, CheckCircle2, Info, Sparkles, TrendingUp } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, StatCard } from "@/components/ui";
import { getDashboardData } from "@/lib/data";

const LEVEL_META = {
  info: { icon: Info, cls: "text-muted-foreground", badge: "outline", label: "Info" },
  success: { icon: CheckCircle2, cls: "text-profit", badge: "profit", label: "Success" },
  warning: { icon: TrendingUp, cls: "text-loss", badge: "loss", label: "Warning" },
  ai: { icon: Sparkles, cls: "text-ai", badge: "ai", label: "AI" },
};

export default function AlertsPage() {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("ALL");
  const [unreadOnly, setUnreadOnly] = useState(false);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
  }, []);

  const alerts = data?.alerts || [];
  const rows = alerts.filter((a) => {
    const matchF = filter === "ALL" || a.level.toUpperCase() === filter;
    const matchU = !unreadOnly || a.unread;
    return matchF && matchU;
  });
  const unread = alerts.filter((a) => a.unread).length;
  const reviews = data?.reviews || [];

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Alerts" value={fmtNum(alerts.length, 0)} subvalue="From the backend" icon={<Bell className="size-4" />} />
        <StatCard label="Unread" value={fmtNum(unread, 0)} subvalue="Needs attention" variant="loss" />
        <StatCard label="System" value={data?.health?.status === "ok" ? "Online" : "Offline"} subvalue={data?.health?.status === "ok" ? "All services healthy" : "Backend unreachable"} variant={data?.health?.status === "ok" ? "profit" : "loss"} />
        <StatCard label="AI Reviews" value={fmtNum(reviews.length, 0)} subvalue="Completed" icon={<Sparkles className="size-4 text-ai" />} variant="ai" />
      </div>

      <Card title="Alerts" subtitle="Derived from real backend signals (AI reviews + system health)">
        <div className="flex items-center gap-2 flex-wrap">
          {["ALL", "AI", "INFO", "SUCCESS", "WARNING"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                filter === f
                  ? "bg-ai/20 text-ai border-ai/30"
                  : "bg-muted/30 text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              {f}
            </button>
          ))}
          <button
            onClick={() => setUnreadOnly((u) => !u)}
            className={`ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
              unreadOnly ? "bg-ai/20 text-ai border-ai/30" : "bg-muted/30 text-muted-foreground border-border"
            }`}
          >
            {unreadOnly ? <Bell className="size-3.5" /> : <BellOff className="size-3.5" />} Unread only
          </button>
        </div>

        {rows.length ? (
          <div className="space-y-2">
            {rows.map((a) => {
              const meta = LEVEL_META[a.level] ?? LEVEL_META.info;
              const Icon = meta.icon;
              return (
                <div key={a.id} className={`rounded-lg border p-3.5 transition-colors ${a.unread ? "bg-ai/5 border-ai/20" : "bg-muted/20 border-border/40"}`}>
                  <div className="flex items-start gap-3">
                    <span className={`mt-0.5 shrink-0 [&>svg]:size-4 ${meta.cls}`}>
                      <Icon />
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold">{a.title}</span>
                        <Badge variant={meta.badge}>{meta.label}</Badge>
                        {a.unread && <span className="size-1.5 rounded-full bg-ai" />}
                      </div>
                      <p className="text-[11px] text-muted-foreground leading-relaxed mt-1">{a.detail}</p>
                      <span className="text-[10px] text-muted-foreground/70 mt-1 block">{a.time} · {a.id}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="py-16 text-center text-xs text-muted-foreground">
            No alerts yet. Alerts appear when the backend produces reviews or health events.
          </div>
        )}
      </Card>
    </AppShell>
  );
}

function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}
