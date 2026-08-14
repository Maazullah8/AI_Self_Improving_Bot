"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FlaskConical, Play, RefreshCw } from "lucide-react";

import AppShell from "@/components/AppShell";
import { EquityChart, MonteCarloChart, WalkForwardChart } from "@/components/charts";
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

const RANGE_PRESETS = [
  { label: "6M", days: 6 * 30 },
  { label: "1Y", days: 365 },
  { label: "2Y", days: 2 * 365 },
  { label: "3Y", days: 3 * 365 },
  { label: "5Y", days: 5 * 365 },
];

function ymd(d) {
  return d.toISOString().slice(0, 10);
}

function ymdToEpoch(ymdStr, endOfDay = false) {
  const [y, m, d] = ymdStr.split("-").map(Number);
  const ts = Date.UTC(y, m - 1, d, endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0);
  return Math.floor(ts / 1000);
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
  const [mcTab, setMcTab] = useState("paths");
  const [timeframe, setTimeframe] = useState("5m");
  const [rangeFrom, setRangeFrom] = useState(() => ymd(new Date(Date.now() - 6 * 30 * 86400)));
  const [rangeTo, setRangeTo] = useState(() => ymd(new Date()));

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
    fetch("/api/data-range?symbol=XAUUSD&timeframe=5m")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d || !d.start || !d.end) return;
        setRangeFrom(ymd(new Date(d.end * 1000 - 6 * 30 * 86400)));
        setRangeTo(ymd(new Date(d.end * 1000)));
      })
      .catch(() => {});
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
    try {
      const r = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: "XAUUSD",
          timeframe,
          start: ymdToEpoch(rangeFrom),
          end: ymdToEpoch(rangeTo, true),
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

  // Monte Carlo equity paths, interpolated across the backtest bar span so the
  // fan chart spans the full period (like the reference dashboards).
  const mcPaths = useMemo(() => {
    const paths = mc?.equity_paths || [];
    const nBars = result?.equity_curve?.length || 0;
    if (!paths.length || nBars < 2) return null;
    const steps = Math.min(220, nBars);
    const rows = [];
    for (let s = 0; s < steps; s++) {
      const bar = Math.round((s * (nBars - 1)) / (steps - 1));
      const row = { bar, pct: Math.round((bar / (nBars - 1)) * 100) };
      paths.forEach((p, pi) => {
        const n = p.length - 1;
        if (n <= 0) {
          row[`p${pi}`] = Math.round(p[0]);
          return;
        }
        const pos = (bar * n) / (nBars - 1);
        const j = Math.min(Math.floor(pos), n - 1);
        row[`p${pi}`] = Math.round(p[j] + (p[j + 1] - p[j]) * (pos - j));
      });
      rows.push(row);
    }
    const keys = paths.map((_, i) => `p${i}`);
    rows.forEach((row) => {
      const vals = keys.map((k) => row[k]).filter((v) => Number.isFinite(v));
      vals.sort((a, b) => a - b);
      row.median = vals[Math.floor(vals.length / 2)];
    });
    return { rows, keys: [...keys, "median"], initial: Math.round(paths[0][0] || 10000) };
  }, [mc, result]);

  // Walk-forward analysis derived from the backend's per-segment run.
  const wf = result?.walk_forward;
  const wfData = wf?.segments ?? [];
  const wfPositive = wf?.consistent ?? false;
  const forwardTest = wf?.generalization_score ?? 0;
  const mcPass = mc?.pass_rate ?? 0;
  const combinedScore = Math.round((forwardTest * 0.5 + mcPass * 0.5) * 100) / 100;
  const wfWindows = [
    ["Training window", wf?.windows?.training ?? "—"],
    ["Validation window", wf?.windows?.validation ?? "—"],
    ["Current performance", wf?.windows?.current_performance ?? "—"],
    ["Consistency", wf ? `${wf.consistency_pct}%` : "—"],
    ["Segments", wf ? `${wf.n_windows} rolling windows` : "—"],
  ];
  const wfSteps = [
    ["Combined Score", combinedScore > 0 ? combinedScore.toFixed(2) : "—", "ai"],
    ["Forward Test", forwardTest > 0 ? (forwardTest / 100).toFixed(2) : "—", "profit"],
    ["Monte Carlo", mcPass > 0 ? (mcPass / 100).toFixed(2) : "—", "ai"],
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
            <div className="space-y-2.5">
              <div>
                <div className="text-[11px] font-medium text-muted-foreground mb-1.5">Date range</div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <label className="block text-[10px] text-muted-foreground mb-0.5">From</label>
                    <input
                      type="date"
                      value={rangeFrom}
                      max={rangeTo}
                      onChange={(e) => setRangeFrom(e.target.value)}
                      className="w-full rounded-md bg-muted/20 border border-border px-2 py-1.5 text-xs tabular-nums"
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <label className="block text-[10px] text-muted-foreground mb-0.5">To</label>
                    <input
                      type="date"
                      value={rangeTo}
                      min={rangeFrom}
                      max={ymd(new Date())}
                      onChange={(e) => setRangeTo(e.target.value)}
                      className="w-full rounded-md bg-muted/20 border border-border px-2 py-1.5 text-xs tabular-nums"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {RANGE_PRESETS.map((p) => {
                    const active = rangeFrom === ymd(new Date(Date.now() - p.days * 86400));
                    return (
                      <button
                        key={p.label}
                        onClick={() => {
                          const now = new Date();
                          setRangeTo(ymd(now));
                          setRangeFrom(ymd(new Date(now.getTime() - p.days * 86400)));
                        }}
                        className={`px-2 py-1 rounded-md text-[10px] font-medium border transition-colors ${
                          active
                            ? "bg-ai/20 text-ai border-ai/30"
                            : "bg-muted/20 text-muted-foreground border-border hover:text-foreground"
                        }`}
                      >
                        {p.label}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[10px] text-muted-foreground mt-1.5">
                  Supports 6 months up to 5 years of data. Use a coarser timeframe for long ranges.
                </p>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1.5">Timeframe</label>
                <div className="flex flex-wrap gap-1.5">
                  {["1m", "5m", "15m", "30m", "1h", "4h"].map((tf) => (
                    <button
                      key={tf}
                      onClick={() => setTimeframe(tf)}
                      className={`px-2 py-1 rounded-md text-[10px] font-medium border transition-colors ${
                        timeframe === tf
                          ? "bg-ai/20 text-ai border-ai/30"
                          : "bg-muted/20 text-muted-foreground border-border hover:text-foreground"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
            </div>

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
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card title="Equity Curve" subtitle={`${result.symbol} ${result.timeframe} · ${fmtNum(metrics.n_trades, 0)} trades`} className="lg:col-span-2">
              {equityData ? (
                <EquityChart data={equityData} height={260} positive={(metrics.final_equity ?? metrics.total_pnl ?? 0) >= 0} />
              ) : (
                <div className="py-16 text-center text-xs text-muted-foreground">No equity curve returned</div>
              )}
            </Card>

            <Card title="Monte Carlo Stats" subtitle="Resampled outcomes from the trade R-distribution">
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

          <Card
            title="Monte Carlo Simulation"
            subtitle={`${mc ? fmtNum(mc.n_sims, 0) : "2,000"} simulations resampled from the actual trade sequence · ${mc ? `${fmtNum(mc.pass_rate, 1)}% pass rate` : "pass rate"}`}
            action={
              <div className="flex items-center gap-1 rounded-md bg-muted/30 border border-border/60 p-0.5">
                {[
                  ["paths", "Equity Paths"],
                  ["distribution", "Return Distribution"],
                ].map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setMcTab(k)}
                    className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
                      mcTab === k ? "bg-ai text-white" : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            }
          >
            {mcTab === "paths" ? (
              mcPaths ? (
                <div className="space-y-2">
                  <MonteCarloChart mode="paths" paths={mcPaths} height={280} />
                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {fmtNum(mcPaths.keys.length - 1, 0)} simulated equity curves across the backtest period.
                    The dashed line marks the initial capital; the bold path is the median outcome.
                  </p>
                </div>
              ) : (
                <div className="py-16 text-center text-xs text-muted-foreground">No equity paths returned</div>
              )
            ) : mc?.distribution?.length ? (
              <div className="space-y-2">
                <MonteCarloChart mode="distribution" distribution={mc.distribution} height={280} />
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Distribution of final returns across simulations. Median return {fmtNum(mc.median_return_pct, 1)}%,
                  95% CI {fmtNum(mc.ci_low_pct, 1)}% to {fmtNum(mc.ci_high_pct, 1)}%.
                </p>
              </div>
            ) : (
              <div className="py-16 text-center text-xs text-muted-foreground">No distribution returned</div>
            )}
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card
              title="Walk Forward Analysis"
              subtitle={`${wf ? `${wf.n_windows} rolling windows · train vs test win rate per segment` : "Rolling window train/test generalization"}`}
              className="lg:col-span-2"
            >
              {wf ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/20 border border-border/40 px-4 py-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Pass Rate</div>
                      <div className="text-4xl font-bold tabular-nums tracking-tight text-profit">{fmtNum(forwardTest, 0)}%</div>
                    </div>
                    <div className="text-right space-y-1">
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-[11px] text-muted-foreground">Current Run</span>
                        <Badge variant={wfPositive ? "profit" : "loss"}>{wfPositive ? "CONSISTENT" : "INCONSISTENT"}</Badge>
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        Validation {wf.windows?.validation ?? "—"} · {wf.n_windows} segments
                      </div>
                    </div>
                  </div>
                  <WalkForwardChart data={wfData} height={250} />
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border/50">
                          <th className="py-2 pr-3 font-medium">Segment</th>
                          <th className="py-2 pr-3 font-medium">Range</th>
                          <th className="py-2 pr-3 font-medium">Train WR</th>
                          <th className="py-2 pr-3 font-medium">Test WR</th>
                          <th className="py-2 pr-3 font-medium">PF</th>
                          <th className="py-2 pr-3 font-medium">Trades</th>
                        </tr>
                      </thead>
                      <tbody>
                        {wfData.map((s) => (
                          <tr key={s.segment} className="border-b border-border/30 hover:bg-white/[0.02]">
                            <td className="py-2.5 pr-3 font-medium text-xs">{s.segment}</td>
                            <td className="py-2.5 pr-3 text-[11px] text-muted-foreground">{s.range}</td>
                            <td className="py-2.5 pr-3 font-semibold tabular-nums text-[11px]">{fmtNum(s.train_win_rate, 1)}%</td>
                            <td className="py-2.5 pr-3 font-semibold tabular-nums text-[11px]">{fmtNum(s.test_win_rate, 1)}%</td>
                            <td className="py-2.5 pr-3 tabular-nums text-[11px]">{fmtNum(s.test_pf, 2)}</td>
                            <td className="py-2.5 pr-3 tabular-nums text-[11px]">{fmtNum(s.test_trades, 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="py-16 text-center text-xs text-muted-foreground">
                  Run a backtest to see walk-forward analysis
                </div>
              )}
            </Card>

            <Card title="Walk Forward Windows" subtitle="Configuration for the current run">
              {wf ? (
                <div className="space-y-4">
                  <div className="space-y-2">
                    {wfWindows.map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">{k}</span>
                        <span className="font-semibold tabular-nums">{v}</span>
                      </div>
                    ))}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {wfSteps.map(([label, value, tone]) => (
                      <div key={label} className="rounded-lg bg-muted/20 border border-border/40 p-3 text-center">
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
                        <div className={`text-lg font-bold tabular-nums ${tone === "profit" ? "text-profit" : "text-ai"}`}>{value}</div>
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Combined Score blends the out-of-sample forward-test win rate with the Monte Carlo
                    pass rate. A consistent strategy keeps train and test win rates close across segments.
                  </p>
                </div>
              ) : (
                <div className="py-16 text-center text-xs text-muted-foreground">
                  Run a backtest to see walk-forward windows
                </div>
              )}
            </Card>
          </div>
        </>
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
