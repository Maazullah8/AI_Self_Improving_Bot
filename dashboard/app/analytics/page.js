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
    { label: "Total Trades", value: hasData ? fmtNum(metrics.totalTrades, 0) : "—", sub: "All time" },
    { label: "Win Rate", value: hasData ? `${fmtNum(metrics.winRate, 1)}%` : "—", sub: "Overall", variant: "profit" },
    { label: "Max Drawdown", value: hasData ? `${fmtNum(metrics.maxDrawdown, 1)}%` : "—", sub: "Depth from peak" },
    { label: "Profit Factor", value: hasData ? fmtNum(metrics.profitFactor, 2) : "—", sub: "Gross win / loss", variant: "profit" },
  ];

  // ----------------------------------------------------------- monthly returns
  const monthly = useMemo(() => {
    const raw = (hasData && metrics?.monthlyReturns) || {};
    const entries = Object.entries(raw).sort((a, b) => (a[0] < b[0] ? -1 : 1));
    return entries.slice(-12).map(([k, v]) => ({
      label: MONTH_ABBR[Number(k.slice(5, 7)) - 1] ?? k.slice(5),
      value: Number(Number(v).toFixed(1)),
    }));
  }, [hasData, metrics]);

  // ----------------------------------------------------------- strategy score
  const radar = useMemo(() => {
    if (!hasData) return [];
    const clamp = (v) => Math.min(Math.max(v, 0), 100);
    return [
      { metric: "Win Rate", value: clamp(metrics.winRate) },
      { metric: "Profit Factor", value: clamp((metrics.profitFactor / 2.4) * 100) },
      { metric: "Sharpe", value: clamp((metrics.sharpe / 2.5) * 100) },
      { metric: "Risk Mgmt", value: clamp(100 - Math.abs(metrics.maxDrawdown) * 1.7) },
      { metric: "Expectancy", value: clamp(50 + metrics.expectancy * 140) },
    ];
  }, [hasData, metrics]);

  // ------------------------------------------------------------ real aggregates
  const weekly = data?.weeklyReturns || [];
  const sessions = data?.sessionAnalysis || [];
  const pairs = data?.pairs || [];
  const daily = data?.dailyReturns || [];
  const monthlyEmpty = !monthly.length;
  const radarEmpty = !radar.length;
  const weeklyEmpty = !weekly.length;
  const sessionsEmpty = !sessions.length;
  const pairsEmpty = !pairs.length;
  const dailyEmpty = !daily.length;

  // --------------------------------------------------------------- risk metrics
  const riskMetrics = [
    ["Sharpe Ratio", hasData ? fmtNum(metrics.sharpe, 2) : "—", "Risk-adjusted return"],
    ["Sortino Ratio", hasData ? fmtNum(metrics.sortino, 2) : "—", "Downside deviation"],
    ["Recovery Factor", hasData ? fmtNum(metrics.recoveryFactor, 1) : "—", "Net profit / max DD"],
    ["Profit Factor", hasData ? fmtNum(metrics.profitFactor, 2) : "—", "Gross profit / loss"],
    ["Expectancy", hasData ? `$${fmtNum(metrics.expectancy, 2)}` : "—", "Avg per trade"],
    ["Avg R:R", hasData ? fmtNum(metrics.avgRR, 2) : "—", "Reward/risk ratio"],
    ["Avg Win", hasData ? `$${fmtNum(metrics.avgWin, 1)}` : "—", "Mean winning trade"],
    ["Avg Loss", hasData ? `-$${fmtNum(metrics.avgLoss, 1)}` : "—", "Mean losing trade"],
    ["Max Consec. Wins", hasData ? fmtNum(metrics.maxConsecWins, 0) : "—", "Longest win streak"],
    ["Max Consec. Losses", hasData ? fmtNum(metrics.maxConsecLosses, 0) : "—", "Longest loss streak"],
    ["Largest Win", hasData ? `$${fmtNum(metrics.largestWin, 1)}` : "—", "Single best trade"],
    ["Largest Loss", hasData ? `-$${fmtNum(metrics.largestLoss, 1)}` : "—", "Single worst trade"],
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
          {monthlyEmpty ? <Empty text="No monthly returns yet — run a backtest to populate." /> : <BarChartSimple data={monthly} height={220} />}
        </Card>

        <Card title="Strategy Score" subtitle="Multi-dimensional performance">
          {radarEmpty ? <Empty text="Run a backtest to see the strategy score." /> : <ScoreRadarChart data={radar} height={220} />}
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title="Weekly Returns" subtitle="Rolling weekly performance">
          {weeklyEmpty ? <Empty text="No weekly returns yet." /> : <BarChartSimple data={weekly} height={180} />}
        </Card>

        <Card title="Session Analysis" subtitle="Performance by trading session">
          {sessionsEmpty ? (
            <Empty text="No session data yet." />
          ) : (
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
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title="Pair Distribution" subtitle="Trade count by instrument">
          {pairsEmpty ? <Empty text="No instrument data yet." /> : <BarChartSimple data={pairs} dataKey="count" colorMode="ai" layout="horizontal" height={200} />}
        </Card>

        <Card title="Daily Returns (Last 30d)" subtitle="Day-by-day P&L %" className="xl:col-span-2">
          {dailyEmpty ? <Empty text="No daily returns yet." /> : <BarChartSimple data={daily} height={200} />}
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
        {!hasData && (
          <p className="text-[11px] text-muted-foreground mt-3">
            No integrated trade data yet — connect your data source and run a backtest to populate these metrics.
          </p>
        )}
      </Card>
    </AppShell>
  );
}

function Empty({ text }) {
  return <div className="flex items-center justify-center h-[220px] text-xs text-muted-foreground text-center px-6">{text}</div>;
}
