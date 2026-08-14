"use client";

import { useEffect, useMemo, useState } from "react";

import AppShell from "@/components/AppShell";
import { BarChartSimple, ScoreRadarChart } from "@/components/charts";
import { Card, StatCard } from "@/components/ui";
import { getDashboardData } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const DEMO = {
  monthly: [
    3.2, -1.1, 5.7, 2.9, -0.8, 4.1, 6.3, -2.4, 3.8, 7.1, 1.9, 4.4,
  ],
  radar: [
    { metric: "Win Rate", value: 78 },
    { metric: "Profit Factor", value: 82 },
    { metric: "Sharpe", value: 74 },
    { metric: "Consistency", value: 68 },
    { metric: "Risk Mgmt", value: 86 },
    { metric: "Expectancy", value: 71 },
  ],
  sessions: [
    { label: "Asian", trades: 41, winRate: 61, avgPnl: 38.2, contribution: 18 },
    { label: "London", trades: 92, winRate: 67.4, avgPnl: 56.7, contribution: 48 },
    { label: "NY", trades: 78, winRate: 63.2, avgPnl: 47.1, contribution: 34 },
    { label: "Overlap", trades: 37, winRate: 59.5, avgPnl: 31.4, contribution: 14 },
  ],
  pairs: [
    { label: "EURUSD", count: 72 },
    { label: "GBPJPY", count: 48 },
    { label: "USDJPY", count: 41 },
    { label: "XAUUSD", count: 35 },
    { label: "GBPUSD", count: 28 },
    { label: "Others", count: 24 },
  ],
};

function demoWeekly() {
  // Deterministic 24-week series (reference uses runtime-random; keep it stable).
  const seed = 11;
  return Array.from({ length: 24 }, (_, i) => ({
    label: `W${i + 1}`,
    value: Number((Math.sin(i * 1.4 + seed) * 3 + Math.sin(i * 0.55) * 1.5).toFixed(1)),
  }));
}

function demoDaily() {
  const seed = 5;
  return Array.from({ length: 30 }, (_, i) => ({
    label: String(i + 1),
    value: Number((Math.sin(i * 1.1 + seed) * 1.4 + Math.sin(i * 0.4) * 0.9).toFixed(1)),
  }));
}

export default function AnalyticsPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
  }, []);

  const metrics = data?.metrics;
  const trades = data?.trades || [];
  const hasData = data?.hasData && metrics?.online && metrics.totalTrades > 0;

  // ---------------------------------------------------------------- stat row
  const stats = [
    {
      label: "Total Trades",
      value: hasData ? fmtNum(metrics.totalTrades, 0) : "248",
      sub: "All time",
    },
    {
      label: "Win Rate",
      value: hasData ? `${fmtNum(metrics.winRate, 1)}%` : "64.2%",
      sub: "Overall",
      variant: "profit",
    },
    {
      label: "Max Drawdown",
      value: hasData ? `${fmtNum(metrics.maxDrawdown, 1)}%` : "-8.4%",
      sub: "Depth from peak",
    },
    {
      label: "Profit Factor",
      value: hasData ? fmtNum(metrics.profitFactor, 2) : "1.94",
      sub: "Gross win / loss",
      variant: "profit",
    },
  ];

  // ----------------------------------------------------------- monthly returns
  const monthly = useMemo(() => {
    const raw = (hasData && metrics?.monthlyReturns) || {};
    const entries = Object.entries(raw).sort((a, b) => (a[0] < b[0] ? -1 : 1));
    if (entries.length) {
      return entries.slice(-12).map(([k, v]) => ({
        label: MONTH_ABBR[Number(k.slice(5, 7)) - 1] ?? k.slice(5),
        value: Number(Number(v).toFixed(1)),
      }));
    }
    return DEMO.monthly.map((v, i) => ({ label: MONTH_ABBR[i], value: v }));
  }, [hasData, metrics]);

  // ----------------------------------------------------------- strategy score
  const radar = useMemo(() => {
    if (!hasData) return DEMO.radar;
    const clamp = (v) => Math.min(Math.max(v, 0), 100);
    return [
      { metric: "Win Rate", value: clamp(metrics.winRate) },
      { metric: "Profit Factor", value: clamp((metrics.profitFactor / 2.4) * 100) },
      { metric: "Sharpe", value: clamp((metrics.sharpe / 2.5) * 100) },
      { metric: "Consistency", value: 68 },
      { metric: "Risk Mgmt", value: clamp(100 - Math.abs(metrics.maxDrawdown) * 1.7) },
      { metric: "Expectancy", value: clamp(50 + metrics.expectancy * 140) },
    ];
  }, [hasData, metrics]);

  // ------------------------------------------------------------- weekly returns
  const weekly = useMemo(() => {
    if (!hasData || trades.length < 40) return demoWeekly();
    const buckets = new Map();
    for (const t of trades) {
      const d = new Date(t.exit_time * 1000);
      const key = `${d.getFullYear()}-W${Math.floor(d.getDate() / 7)}`;
      buckets.set(key, (buckets.get(key) || 0) + (t.pnl || 0));
    }
    const sorted = [...buckets.entries()].slice(-24);
    return sorted.map(([k, v], i) => ({
      label: `W${i + 1}`,
      value: Number((v / 100).toFixed(1)),
    }));
  }, [hasData, trades]);

  // ------------------------------------------------------------- session analysis
  const sessions = useMemo(() => {
    if (!hasData || trades.length < 40) return DEMO.sessions;
    const bySession = new Map();
    let totalPnl = 0;
    for (const t of trades) {
      const s = String(t.session || "Other");
      const b = bySession.get(s) || { n: 0, wins: 0, pnl: 0 };
      b.n += 1;
      b.pnl += t.pnl || 0;
      if ((t.pnl || 0) > 0) b.wins += 1;
      totalPnl += t.pnl || 0;
      bySession.set(s, b);
    }
    return [...bySession.entries()]
      .map(([label, b]) => ({
        label,
        trades: b.n,
        winRate: Number(((b.wins / b.n) * 100).toFixed(1)),
        avgPnl: Number((b.pnl / b.n).toFixed(1)),
        contribution: totalPnl ? Number(((b.pnl / totalPnl) * 100).toFixed(0)) : 0,
      }))
      .sort((a, b) => b.contribution - a.contribution);
  }, [hasData, trades]);

  // ----------------------------------------------------------- pair distribution
  const pairs = useMemo(() => {
    if (!hasData || trades.length < 40) return DEMO.pairs;
    const bySym = new Map();
    for (const t of trades) {
      bySym.set(t.symbol, (bySym.get(t.symbol) || 0) + 1);
    }
    const rows = [...bySym.entries()].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count);
    if (rows.length <= 1) return DEMO.pairs;
    return rows.slice(0, 5).concat(
      rows.length > 5
        ? [{ label: "Others", count: rows.slice(5).reduce((a, b) => a + b.count, 0) }]
        : [],
    );
  }, [hasData, trades]);

  // ------------------------------------------------------------ daily returns
  const daily = useMemo(() => {
    if (!hasData || trades.length < 40) return demoDaily();
    const buckets = new Map();
    for (const t of trades) {
      const d = new Date(t.exit_time * 1000);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      buckets.set(key, (buckets.get(key) || 0) + (t.pnl || 0));
    }
    const sorted = [...buckets.entries()].slice(-30);
    return sorted.map(([, v], i) => ({
      label: String(i + 1),
      value: Number((v / 100).toFixed(1)),
    }));
  }, [hasData, trades]);

  // --------------------------------------------------------------- risk metrics
  const riskMetrics = [
    ["Sharpe Ratio", hasData ? fmtNum(metrics.sharpe, 2) : "1.87", "Risk-adjusted return"],
    ["Sortino Ratio", hasData ? fmtNum(metrics.sortino, 2) : "2.34", "Downside deviation"],
    ["Calmar Ratio", "1.12", "Return / max DD"],
    ["Recovery Factor", hasData ? fmtNum(metrics.recoveryFactor, 1) : "3.4", "Net profit / max DD"],
    ["Profit Factor", hasData ? fmtNum(metrics.profitFactor, 2) : "1.94", "Gross profit / loss"],
    ["Expectancy", hasData ? `$${fmtNum(metrics.expectancy, 2)}` : "$48.32", "Avg per trade"],
    ["Avg R:R", hasData ? fmtNum(metrics.avgRR, 2) : "1.68", "Reward/risk ratio"],
    ["Avg Win", hasData ? `$${fmtNum(metrics.avgWin, 1)}` : "$187.4", "Mean winning trade"],
    ["Avg Loss", hasData ? `-$${fmtNum(metrics.avgLoss, 1)}` : "-$111.6", "Mean losing trade"],
    ["Avg Duration", "3h 24m", "Trade hold time"],
    ["Max Consec. Wins", hasData ? fmtNum(metrics.maxConsecWins, 0) : "9", "Longest win streak"],
    ["Max Consec. Losses", hasData ? fmtNum(metrics.maxConsecLosses, 0) : "4", "Longest loss streak"],
    ["Largest Win", hasData ? `$${fmtNum(metrics.largestWin, 1)}` : "$748.2", "Single best trade"],
    ["Largest Loss", hasData ? `-$${fmtNum(metrics.largestLoss, 1)}` : "-$312.4", "Single worst trade"],
  ];

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {stats.map((s) => (
          <StatCard key={s.label} label={s.label} value={s.value} subvalue={s.sub} variant={s.variant || "default"} />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title="Monthly Returns" subtitle="% gain/loss per month" className="xl:col-span-2">
          <BarChartSimple data={monthly} height={220} />
        </Card>

        <Card title="Strategy Score" subtitle="Multi-dimensional performance">
          <ScoreRadarChart data={radar} height={220} />
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title="Weekly Returns" subtitle="Rolling weekly performance">
          <BarChartSimple data={weekly} height={180} />
        </Card>

        <Card title="Session Analysis" subtitle="Performance by trading session">
          <div className="space-y-3 mt-2">
            {sessions.map((s) => (
              <div key={s.label} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-foreground/90">{s.label}</span>
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {s.trades} trades · <span className="text-profit">{s.winRate}% WR</span> ·{" "}
                    <span className="font-semibold text-foreground/90">${fmtNum(s.avgPnl, 1)} avg</span>
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-muted/60 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-ai transition-all duration-500"
                    style={{ width: `${Math.min(Math.max(s.contribution, 0), 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title="Pair Distribution" subtitle="Trade count by instrument">
          <BarChartSimple data={pairs} dataKey="count" colorMode="ai" layout="horizontal" height={200} />
        </Card>

        <Card title="Daily Returns (Last 30d)" subtitle="Day-by-day P&L %" className="xl:col-span-2">
          <BarChartSimple data={daily} height={200} />
        </Card>
      </div>

      <Card title="Risk Metrics" subtitle="Complete performance statistics">
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
          {riskMetrics.map(([label, value, info]) => (
            <div key={label} className="rounded-lg bg-muted/10 border border-border/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
              <div className="text-base font-bold tabular-nums text-foreground">{value}</div>
              <div className="text-[10px] text-muted-foreground/70 mt-0.5">{info}</div>
            </div>
          ))}
        </div>
      </Card>
    </AppShell>
  );
}
