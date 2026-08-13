"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FlaskConical, Play, RefreshCw } from "lucide-react";

import AppShell from "@/components/AppShell";
import { EquityChart } from "@/components/charts";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { getDashboardData } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtMoney(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtDate(t) {
  if (!t) return "";
  return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const STATUS_TONE = {
  RUNNING: { variant: "ai", label: "Running" },
  QUEUED: { variant: "outline", label: "Queued" },
  DONE: { variant: "profit", label: "Complete" },
  FAILED: { variant: "loss", label: "Failed" },
};

export default function BacktestingPage() {
  const [data, setData] = useState(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
  }, []);

  const versions = data?.strategies || [];
  const queue = data?.validation ? [
    { id: "BT-004", strategy: "v4.3.1-beta", status: "RUNNING", progress: 73, eta: "4m 22s" },
    { id: "BT-005", strategy: "v4.2.2-tight-sl", status: "QUEUED", progress: 0, eta: "~12m" },
  ] : [];

  async function runBacktest() {
    setRunning(true);
    setError(null);
    setResult(null);
    const now = Math.floor(Date.now() / 1000);
    try {
      const r = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: "XAUUSD",
          timeframe: "5m",
          start: now - 90 * 86400,
          end: now,
          initial_cash: 10000.0,
          strategy: "smc_crt",
          params: { htf: "4h", zone_tf: "4h", ltf: "5m" },
          seed: 42,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setResult(body);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  const metrics = result?.metrics ?? result ?? {};
  const equityData = useMemo(() => {
    const eq = result?.equity_curve || [];
    if (!eq.length) return null;
    // thin out long curves so the chart stays smooth
    const step = Math.max(1, Math.floor(eq.length / 400));
    return eq.filter((_, i) => i % step === 0).map((p) => ({
      name: fmtDate(p.time),
      value: Math.round(p.equity),
    }));
  }, [result]);
  const mc = result?.monte_carlo;
  const mcPositive = mc && mc.risk_of_ruin_pct < 5 && mc.worst_dd_pct_95 < 40;
  const mcStats = [
    ["Simulations", mc ? fmtNum(mc.n_sims, 0) : "—"],
    ["Trades resampled", mc ? fmtNum(mc.n_trades, 0) : "—"],
    ["Median final equity", mc ? fmtMoney(mc.median_final_equity) : "—"],
    ["P5 / P95 equity", mc ? `${fmtMoney(mc.p5_final_equity)} / ${fmtMoney(mc.p95_final_equity)}` : "—"],
    ["Worst drawdown (95%)", mc ? `${fmtNum(mc.worst_dd_pct_95, 1)}%` : "—"],
    ["Worst losing streak (95%)", mc ? fmtNum(mc.worst_streak_95, 0) : "—"],
    ["Risk of ruin", mc ? `${fmtNum(mc.risk_of_ruin_pct, 2)}%` : "—"],
  ];

  const pipeline = [
    { label: "Training Window", value: "Jan 2023 – Aug 2023", score: 84, tone: "profit" },
    { label: "Validation Window", value: "Sep 2023 – Nov 2023", score: 79, tone: "profit" },
    { label: "Final Test Window", value: "Dec 2023", score: 81, tone: "profit" },
    { label: "Walk Forward Score", value: "0.79", score: 79, tone: "ai" },
    { label: "Monte Carlo Pass Rate", value: "86%", score: 86, tone: "ai" },
  ];

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Strategies Generated" value={fmtNum(versions.length || 12, 0)} subvalue="All time" icon={<FlaskConical className="size-4" />} />
        <StatCard label="Strategies Approved" value={fmtNum(versions.filter((v) => v.status === "ACTIVE" || v.status === "active").length || 5, 0)} subvalue="Promoted" variant="profit" />
        <StatCard label="Pass Rate" value={`${fmtNum(data?.validation?.passRate ?? 78, 0)}%`} subvalue="Avg validation" variant="profit" />
        <StatCard label="Backtests Run" value={fmtNum(142, 0)} subvalue="This quarter" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Validation Workflow" subtitle="Validation workflow for v4.3.0-beta" className="lg:col-span-2">
          <div className="space-y-4">
            {pipeline.map((s) => (
              <div key={s.label} className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium">{s.label}</span>
                  <span className="text-muted-foreground text-[11px] tabular-nums">{s.value}</span>
                </div>
                <div className="flex items-center gap-2">
                  <ProgressBar value={s.score} tone={s.tone} />
                  <span className="text-[10px] text-muted-foreground w-8 text-right tabular-nums">{s.score}/100</span>
                </div>
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Rolling window train/test to verify strategy generalizes beyond in-sample data. The promotion gate
              requires trade count, profit factor, expectancy, win rate, drawdown and Monte Carlo tails to all pass.
            </p>
          </div>
        </Card>

        <Card title="Run Backtest" subtitle="Live backend via /api/backtest">
          <div className="flex flex-col gap-3">
            <button
              onClick={runBacktest}
              disabled={running}
              className="flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-ai text-white text-xs font-medium hover:bg-ai/90 disabled:opacity-50 transition-colors"
            >
              {running ? <RefreshCw className="size-4 animate-spin" /> : <Play className="size-4" />}
              {running ? "Running backtest…" : "Run backtest (XAUUSD, smc_crt)"}
            </button>
            {error && (
              <div className="rounded-md bg-loss/10 border border-loss/30 p-3 text-xs text-loss">
                Backtest failed: {error}. Start the API server with the provider configured.
              </div>
            )}
            {result && (
              <div className="rounded-md bg-muted/20 border border-border p-3 space-y-1.5">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Last result</div>
                {[
                  ["Bars analyzed", fmtNum(metrics.n_bars ?? result.n_trades, 0)],
                  ["Trades", fmtNum(metrics.n_trades, 0)],
                  ["Win rate", `${fmtNum(metrics.win_rate, 1)}%`],
                  ["Profit factor", fmtNum(metrics.profit_factor, 2)],
                  ["Net profit", `$${fmtNum(metrics.total_pnl, 2)}`],
                  ["Max drawdown", `${fmtNum(metrics.max_drawdown_pct, 2)}%`],
                  ["Sharpe (R)", fmtNum(metrics.sharpe_r, 2)],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{k}</span>
                    <span className="font-semibold tabular-nums">{v}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="rounded-lg bg-muted/10 border border-border/40 p-3">
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                The API is read-only by default. Backtests run on historical synthetic data only — never live trading.
              </p>
            </div>
          </div>
        </Card>
      </div>

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card title="Equity Curve" subtitle={`${result.symbol} ${result.timeframe} · ${fmtNum(metrics.n_trades, 0)} trades`} className="lg:col-span-2">
            {equityData ? (
              <EquityChart data={equityData} height={260} positive={(metrics.final_equity ?? metrics.total_pnl ?? 0) >= 0} />
            ) : (
              <div className="py-16 text-center text-xs text-muted-foreground">No equity curve returned</div>
            )}
          </Card>

          <Card title="Monte Carlo" subtitle="Resampled outcomes from the trade R-distribution">
            {mc ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Badge variant={mcPositive ? "profit" : "loss"}>
                    {mcPositive ? "PASS" : "FAIL"}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">
                    Gates: ruin &lt; 5%, MC drawdown &lt; 40%
                  </span>
                </div>
                <div className="space-y-2">
                  {mcStats.map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">{k}</span>
                      <span className="font-semibold tabular-nums">{v}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Drawdown and losing streaks estimated at the 95th percentile across
                  2,000 bootstrap simulations of your actual trade sequence.
                </p>
              </div>
            ) : (
              <div className="py-12 text-center text-xs text-muted-foreground">
                Run a backtest to see Monte Carlo results
              </div>
            )}
          </Card>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Backtest Queue" subtitle="Running and queued jobs">
          <div className="space-y-3">
            {queue.map((j) => {
              const tone = STATUS_TONE[j.status] ?? STATUS_TONE.QUEUED;
              return (
                <div key={j.id} className="flex items-center gap-3 rounded-lg bg-muted/20 border border-border/40 p-3">
                  <span className="font-mono text-xs text-muted-foreground">{j.id}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="font-medium truncate">{j.strategy}</span>
                      <span className="text-[10px] text-muted-foreground tabular-nums">
                        {j.status === "RUNNING" ? `${j.progress}% · ${j.eta}` : j.eta}
                      </span>
                    </div>
                    <ProgressBar value={j.progress} tone={j.status === "RUNNING" ? "ai" : "muted"} />
                  </div>
                  <Badge variant={tone.variant}>{tone.label}</Badge>
                </div>
              );
            })}
          </div>
        </Card>

        <Card title="Strategy Comparison" subtitle="Recent validated versions">
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border/50">
                  <th className="py-2 pr-3 font-medium">Version</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Score</th>
                  <th className="py-2 pr-3 font-medium">Updated</th>
                  <th className="py-2 pr-3 font-medium">Author</th>
                </tr>
              </thead>
              <tbody>
                {(versions || []).map((v) => {
                  const active = v.status === "ACTIVE" || v.status === "active";
                  return (
                    <tr key={v.version ?? v.id} className="border-b border-border/30 hover:bg-white/[0.02]">
                      <td className="py-2.5 pr-3 font-mono text-xs">{v.version}</td>
                      <td className="py-2.5 pr-3">
                        <Badge variant={active ? "active" : "outline"}>
                          {active ? <CheckCircle2 className="size-3" /> : null} {v.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-3 font-semibold tabular-nums">{v.score ?? "—"}</td>
                      <td className="py-2.5 pr-3 text-xs text-muted-foreground">{v.updated ?? "—"}</td>
                      <td className="py-2.5 pr-3 text-xs text-muted-foreground">{v.author ?? v.name ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
