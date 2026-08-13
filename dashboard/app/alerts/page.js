"use client";

import { useState } from "react";
import { Bell, BellOff, CheckCircle2, Info, Sparkles, TrendingUp } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, StatCard } from "@/components/ui";

const ALL_ALERTS = [
  { id: "AL-101", level: "ai", title: "New AI learning cycle complete", time: "2 min ago", unread: true, detail: "Cycle 148 reviewed 248 trades at 47 trades/min. Pattern confidence 78.4%." },
  { id: "AL-100", level: "info", title: "Market regime shift detected", time: "18 min ago", unread: true, detail: "Trend regime confirmed on EURUSD 4H. Adjusting HTF bias for London session." },
  { id: "AL-099", level: "success", title: "Strategy v4.2.1 performing above expectation", time: "1h ago", unread: false, detail: "Win rate 64.2% vs expected 60%. Monte Carlo confidence: 89%." },
  { id: "AL-098", level: "warning", title: "Trade T-247 stopped out. AI flagged for review.", time: "3h ago", unread: false, detail: "SL hit. Spread widened during news, entry was poorly timed." },
  { id: "AL-097", level: "info", title: "Strategy v4.3.0-beta completed 2000-iteration Monte Carlo.", time: "5h ago", unread: false, detail: "Median return 12.4%, worst simulation -6.8%. Pass rate 86%." },
  { id: "AL-096", level: "success", title: "Walk-forward validation passed for v4.2.1", time: "8h ago", unread: false, detail: "Consistent train/test performance across 12 windows. Overfitting risk: low." },
  { id: "AL-095", level: "info", title: "Trailing stop management working as expected", time: "12h ago", unread: false, detail: "Trade management was disciplined. Trailing stop worked as designed." },
  { id: "AL-094", level: "warning", title: "NY overlap caused fakeout on GBPJPY", time: "1d ago", unread: false, detail: "Liquidity sweep was deeper than expected. Reviewing skip rule during overlap." },
];

const LEVEL_META = {
  info: { icon: Info, cls: "text-muted-foreground", badge: "outline", label: "Info" },
  success: { icon: CheckCircle2, cls: "text-profit", badge: "profit", label: "Success" },
  warning: { icon: TrendingUp, cls: "text-loss", badge: "loss", label: "Warning" },
  ai: { icon: Sparkles, cls: "text-ai", badge: "ai", label: "AI" },
};

export default function AlertsPage() {
  const [filter, setFilter] = useState("ALL");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const rows = ALL_ALERTS.filter((a) => {
    const matchF = filter === "ALL" || a.level.toUpperCase() === filter;
    const matchU = !unreadOnly || a.unread;
    return matchF && matchU;
  });
  const unread = ALL_ALERTS.filter((a) => a.unread).length;

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Alerts" value={fmtNum(ALL_ALERTS.length, 0)} subvalue="Last 24h" icon={<Bell className="size-4" />} />
        <StatCard label="Unread" value={fmtNum(unread, 0)} subvalue="Needs attention" variant="loss" />
        <StatCard label="System" value="Online" subvalue="All services healthy" variant="profit" />
        <StatCard label="AI Cycles" value="148" subvalue="Completed" icon={<Sparkles className="size-4 text-ai" />} variant="ai" />
      </div>

      <Card title="Alerts" subtitle={`${unread} unread notifications`} action={<Badge variant="ai">{unread} new</Badge>}>
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
          {!rows.length && <div className="py-16 text-center text-xs text-muted-foreground">No alerts matching this filter.</div>}
        </div>
      </Card>
    </AppShell>
  );
}

function fmtNum(v, digits = 0) {
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}
