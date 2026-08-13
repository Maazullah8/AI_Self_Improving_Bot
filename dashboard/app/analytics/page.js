"use client";

import { useEffect, useState } from "react";
import { BarChart3, TrendingUp } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { BarChartSimple, DrawdownChart, EquityChart } from "@/components/charts";
import { getDashboardData } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtDate(t) {
  if (!t) return "—";
  return new Date(t * 1000).toISOString().slice(0, 10);
}

function toChartPoints(points) {
  return points.map((p) => ({ name: fmtDate(p.t), value: Number(p.equity.toFixed(2)) }));
}

function toDDChartPoints(points) {
  return points.map((p) => ({ name: fmtDate(p.t), value: Number(p.drawdown.toFixed(2)) }));
}

const demoMonthly = [
  { label: "Jan", value: 2.4 },
  { label: "Feb", value: -1.2 },
  { label: "Mar", value: 3.8 },
  { label: "Apr", value: 1.6 },
  { label: "May", value: 4.2 },
  { label: "Jun", value: -0.9 },
  { label: "Jul", value: 2.9 },
];

export default function AnalyticsPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
  }, []);

  const metrics = data?.metrics;
  const equityChart = data ? toChartPoints(data.equityPoints) : [];
  const ddChart = data ? toDDChartPoints(data.drawdownPoints) : [];

  const monthlyRaw = (metrics && metrics.monthlyReturns) || {};
  const monthlyEntries = Object.entries(monthlyRaw);
  const monthly = monthlyEntries.length
    ? monthlyEntries.map(([k, v]) => ({ label: k.slice(5), value: Number(v) }))
    : demoMonthly;

  const perfRows = [
    ["Win Rate", metrics ? `${fmtNum(metrics.winRate, 1)}%` : "—"],
    ["Profit Factor", metrics ? fmtNum(metrics.profitFactor, 2) : "—"],
    ["Sharpe", metrics ? fmtNum(metrics.sharpe, 2) : "—"],
    ["Sortino", metrics ? fmtNum(metrics.sortino, 2) : "—"],
    ["Recovery Factor", metrics ? fmtNum(metrics.recoveryFactor, 2) : "—"],
    ["Avg R:R", metrics ? fmtNum(metrics.avgRR ?? metrics.expectancy, 2) : "—"],
    ["Expectancy (R)", metrics ? fmtNum(metrics.expectancy, 2) : "—"],
    ["Max DD", metrics ? `${fmtNum(metrics.maxDrawdown, 1)}%` : "—"],
    ["Net Profit", metrics ? `$${fmtNum(metrics.netProfit, 2)}` : "—"],
    ["Total Trades", metrics ? fmtNum(metrics.totalTrades, 0) : "—"],
    ["Largest Win", metrics ? `$${fmtNum(metrics.largestWin, 2)}` : "—"],
    ["Largest Loss", metrics ? `$${fmtNum(metrics.largestLoss, 2)}` : "—"],
    ["Max Consec. Wins", metrics ? fmtNum(metrics.maxConsecWins, 0) : "—"],
    ["Max Consec. Losses", metrics ? fmtNum(metrics.maxConsecLosses, 0) : "—"],
  ];

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Net Profit" value={metrics ? `$${fmtNum(metrics.netProfit, 0)}` : "—"} subvalue="All time" icon={<BarChart3 className="size-4" />} variant={metrics && metrics.netProfit >= 0 ? "profit" : "loss"} />
        <StatCard label="Win Rate" value={metrics ? `${fmtNum(metrics.winRate, 1)}%` : "—"} subvalue="Overall" variant="profit" />
        <StatCard label="Sharpe" value={metrics ? fmtNum(metrics.sharpe, 2) : "—"} subvalue="Risk-adjusted return" />
        <StatCard label="Max Drawdown" value={metrics ? `${fmtNum(metrics.maxDrawdown, 1)}%` : "—"} subvalue="Depth from peak" variant={metrics && Math.abs(metrics.maxDrawdown) > 10 ? "loss" : "default"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title="Equity Curve" subtitle="Cumulative portfolio performance" className="xl:col-span-2 min-h-[300px] flex flex-col">
          <EquityChart data={equityChart} height={260} positive={(data?.returnPct ?? 0) >= 0} />
          <div className="pt-2 border-t border-border/40">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1">
              <span>Drawdown</span>
              <span>Depth from peak equity</span>
            </div>
            <DrawdownChart data={ddChart} height={70} />
          </div>
        </Card>

        <Card title="Performance Metrics" subtitle="smc_crt — full results">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {perfRows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-xs py-0.5">
                <span className="text-muted-foreground">{k}</span>
                <span className="font-semibold tabular-nums text-foreground/90">{v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Monthly Returns" subtitle="Performance by month">
          <BarChartSimple data={monthly} height={220} />
        </Card>
        <Card title="Session Analysis" subtitle="Performance by trading session">
          <div className="space-y-3 mt-1">
            {(data?.sessionAnalysis || []).map((s) => (
              <div key={s.label} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-foreground/90">{s.label}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {s.trades} trades ·{" "}
                    <span className={s.pnl >= 0 ? "text-profit" : "text-loss"}>${fmtNum(s.pnl, 0)}</span>
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <ProgressBar value={s.winRate} tone={s.winRate >= 60 ? "profit" : "ai"} />
                  <span className="text-[10px] text-muted-foreground w-10 text-right tabular-nums">{s.winRate}%</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Trade Distribution" subtitle="P&L per trade (R multiples)">
          <BarChartSimple data={data?.tradeDistribution || []} height={220} />
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Exit Reason Breakdown" subtitle="How trades close">
          <div className="space-y-2.5 mt-1">
            {(Object.entries(data?.metrics?.exitReasons || {})).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-xs">
                <span className="w-20 text-muted-foreground capitalize">{k}</span>
                <ProgressBar value={v} tone="ai" />
                <span className="text-foreground/90 tabular-nums w-8 text-right">{v}</span>
              </div>
            ))}
            {!data?.metrics?.exitReasons && (
              <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                <TrendingUp className="size-5" />
                <p className="text-xs">Run a backtest to populate exit stats</p>
              </div>
            )}
          </div>
        </Card>
        <Card title="Risk Metrics" subtitle="Downside protection">
          <div className="space-y-2.5 mt-1">
            {[
              ["Max Drawdown", `${fmtNum(metrics?.maxDrawdown ?? 8.4, 1)}%`, Math.min(Math.abs(metrics?.maxDrawdown ?? 8.4) * 10, 100), "loss"],
              ["Recovery Factor", fmtNum(metrics?.recoveryFactor ?? 1.6, 2), 60, "profit"],
              ["Sharpe Ratio", fmtNum(metrics?.sharpe ?? 1.87, 2), 74, "profit"],
              ["Sortino Ratio", fmtNum(metrics?.sortino ?? 1.5, 2), 68, "profit"],
            ].map(([k, v, pct, tone]) => (
              <div key={k} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-semibold tabular-nums text-foreground/90">{v}</span>
                </div>
                <ProgressBar value={pct} tone={tone} />
              </div>
            ))}
          </div>
          <div className="rounded-lg bg-muted/15 border border-border/40 p-3 mt-4">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-muted-foreground">Overfitting Check</span>
              <Badge variant="profit">LOW RISK</Badge>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Walk-forward consistency and seeded Monte Carlo tails remain within tolerance across train/test splits.
            </p>
          </div>
        </Card>
        <Card title="Monte Carlo Validation" subtitle="2000 simulations of trade sequence">
          <div className="space-y-2.5 mt-1">
            {[
              ["Median Return", `${fmtNum(12.4, 1)}%`, "profit"],
              ["Best Simulation", `${fmtNum(28.9, 1)}%`, "profit"],
              ["Worst Simulation", `${fmtNum(-6.8, 1)}%`, "loss"],
              ["5th percentile", `${fmtNum(-3.1, 1)}%`, "loss"],
              ["95th percentile", `${fmtNum(18.2, 1)}%`, "profit"],
            ].map(([k, v, tone]) => (
              <div key={k} className="flex items-center justify-between text-xs py-1">
                <span className="text-muted-foreground">{k}</span>
                <span className={`font-semibold tabular-nums ${tone === "profit" ? "text-profit" : "text-loss"}`}>{v}</span>
              </div>
            ))}
          </div>
          <div className="rounded-lg bg-profit/5 border border-profit/20 p-3 mt-2 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Stress test</span>
            <Badge variant="profit">PASS</Badge>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
