"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  Bell,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock,
  Crosshair,
  FlaskConical,
  Info,
  Sparkles,
  Target,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { BarChartSimple, DrawdownChart, EquityChart, TrendLineChart } from "@/components/charts";
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

function AnalysisRow({ label, value, icon }) {
  return (
    <div className="flex items-center justify-between text-xs py-1.5">
      <span className="flex items-center gap-2 text-muted-foreground">
        <span className="text-muted-foreground/70 [&>svg]:size-3.5">{icon}</span>
        {label}
      </span>
      <span className="font-medium text-foreground tabular-nums">{value}</span>
    </div>
  );
}

function PositionRow({ p }) {
  const long = p.direction === "LONG";
  const green = p.pnl >= 0;
  return (
    <div className="flex items-center gap-3 py-2 border-b border-border/30 last:border-0">
      <div className="w-10 shrink-0">
        <Badge variant={long ? "profit" : "loss"}>{p.direction}</Badge>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold">{p.pair}</span>
          <span className="text-[10px] text-muted-foreground font-mono">{p.id}</span>
        </div>
        <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
          {fmtNum(p.entryPrice, p.entryPrice < 10 ? 5 : 3)} → {fmtNum(p.currentPrice, p.currentPrice < 10 ? 5 : 3)}
          <span className="mx-1 text-muted-foreground/50">·</span>SL {fmtNum(p.sl, p.sl < 10 ? 5 : 3)}
          <span className="mx-1 text-muted-foreground/50">·</span>TP {fmtNum(p.tp, p.tp < 10 ? 5 : 3)}
        </div>
      </div>
      <div className="hidden sm:block text-right shrink-0">
        <div className="text-xs text-muted-foreground tabular-nums">{p.openTime}</div>
        <div className="text-[10px] text-muted-foreground/70 flex items-center justify-end gap-1">
          <Clock className="size-3" /> {p.duration}
        </div>
      </div>
      <div className="text-right shrink-0 w-20">
        <div className={`text-xs font-bold tabular-nums ${green ? "text-profit" : "text-loss"}`}>
          {p.pnl >= 0 ? "+" : ""}
          {fmtNum(p.pnl, 2)}
        </div>
        <div className={`text-[10px] tabular-nums ${green ? "text-profit/70" : "text-loss/70"}`}>
          {p.pnlPct >= 0 ? "+" : ""}
          {fmtNum(p.pnlPct, 2)}%
        </div>
      </div>
    </div>
  );
}

function alertIcon(level) {
  switch (level) {
    case "success":
      return { icon: CheckCircle2, cls: "text-profit" };
    case "warning":
      return { icon: Bell, cls: "text-loss" };
    case "ai":
      return { icon: Sparkles, cls: "text-ai" };
    default:
      return { icon: Info, cls: "text-muted-foreground" };
  }
}

function AlertRow({ a }) {
  const { icon: Icon, cls } = alertIcon(a.level);
  return (
    <div className="flex items-start gap-2.5 py-2">
      <span className={`mt-0.5 shrink-0 [&>svg]:size-3.5 ${cls}`}>
        <Icon />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs leading-snug text-foreground/90">{a.title}</p>
        <span className="text-[10px] text-muted-foreground">{a.time}</span>
      </div>
      {a.unread && <span className="size-1.5 rounded-full bg-ai shrink-0 mt-1.5" />}
    </div>
  );
}

const pipelineMeta = {
  done: { icon: CheckCircle2, cls: "text-profit", label: "Complete" },
  active: { icon: Zap, cls: "text-ai", label: "Running" },
  pending: { icon: Clock, cls: "text-muted-foreground", label: "Pending" },
};

export default function Page() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    getDashboardData()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  if (err) {
    return (
      <AppShell>
        <div className="flex flex-col items-center gap-3 py-24 text-muted-foreground">
          <Crosshair className="size-8" />
          <p className="text-sm">Failed to load dashboard data: {err}</p>
        </div>
      </AppShell>
    );
  }

  if (!data) {
    return (
      <AppShell>
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="card-elevated p-4 h-[96px] animate-pulse" />
          ))}
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="card-elevated xl:col-span-2 p-5 h-[320px] animate-pulse" />
          <div className="card-elevated p-5 h-[320px] animate-pulse" />
        </div>
      </AppShell>
    );
  }

  const { cards, equityPoints, drawdownPoints, returnPct, aiAnalysis } = data;
  const equityChart = toChartPoints(equityPoints);
  const ddChart = toDDChartPoints(drawdownPoints);
  const positive = returnPct >= 0;

  return (
    <AppShell>
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
        <StatCard
          label="Equity"
          value={`$${fmtNum(cards.equity, 2)}`}
          subvalue="Real-time balance"
          icon={<Wallet className="size-4" />}
          variant="profit"
        />
        <StatCard
          label="Today's P&L"
          value={`${cards.todayPnL >= 0 ? "+" : ""}$${fmtNum(cards.todayPnL, 2)}`}
          subvalue={`${cards.todayPnLPct >= 0 ? "+" : ""}${fmtNum(cards.todayPnLPct, 2)}%`}
          trend={cards.todayPnL >= 0 ? "up" : "down"}
          trendValue={`${fmtNum(Math.abs(cards.todayPnLPct), 1)}%`}
          variant={cards.todayPnL >= 0 ? "profit" : "loss"}
        />
        <StatCard
          label="Win Rate"
          value={`${fmtNum(cards.winRate, 1)}%`}
          subvalue="Last 30 days"
          trend="up"
          trendValue="+2.1%"
        />
        <StatCard
          label="Max Drawdown"
          value={`${fmtNum(cards.maxDrawdown, 1)}%`}
          subvalue="Threshold: -10%"
          trend="neutral"
          trendValue="Safe"
          variant={Math.abs(cards.maxDrawdown) > 10 ? "loss" : "default"}
        />
        <StatCard label="Sharpe Ratio" value={fmtNum(cards.sharpeRatio, 2)} subvalue="Annualized" />
        <StatCard label="Profit Factor" value={fmtNum(cards.profitFactor, 2)} subvalue="Gross P/L ratio" />
        <StatCard
          label="AI Confidence"
          value={`${fmtNum(cards.aiConfidence, 0)}%`}
          subvalue="Current cycle"
          trend="up"
          trendValue="+3%"
          variant="ai"
          icon={<Sparkles className="size-4 text-ai" />}
        />
      </div>

      {/* Equity curve + AI analysis */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card
          title="Equity Curve"
          subtitle="Cumulative portfolio performance"
          className="xl:col-span-2 min-h-[300px] flex flex-col"
          action={
            <span className="flex items-center gap-1.5 text-[11px] text-profit font-medium">
              <TrendingUp className="size-3" />
              {positive ? "+" : ""}
              {fmtNum(returnPct, 1)}% all-time
            </span>
          }
        >
          <EquityChart data={equityChart} height={240} positive={positive} />
          <div className="pt-2 border-t border-border/40">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1">
              <span>Drawdown</span>
              <span>Depth from peak equity</span>
            </div>
            <DrawdownChart data={ddChart} height={70} />
          </div>
        </Card>

        <Card
          title="AI Analysis"
          subtitle="Current market interpretation"
          className="p-5"
          action={<Badge variant="ai" className="text-[10px]">{aiAnalysis.confidence}% conf</Badge>}
        >
          <div className="space-y-0.5">
            <AnalysisRow label="Market Regime" value={aiAnalysis.marketRegime} icon={<Activity className="size-4" />} />
            <AnalysisRow label="Trend" value={aiAnalysis.marketCondition} icon={<TrendingUp className="size-4" />} />
            <AnalysisRow label="Setup Type" value={aiAnalysis.setupType} icon={<Crosshair className="size-4" />} />
            <AnalysisRow label="HTF Bias" value={aiAnalysis.htfBias} icon={<BrainCircuit className="size-4" />} />
            <AnalysisRow label="LTF Confirmation" value={aiAnalysis.ltfConfirmation} icon={<Target className="size-4" />} />
          </div>
          <div className="rounded-lg bg-muted/15 border border-border/40 p-3">
            <p className="text-xs text-muted-foreground leading-relaxed">{aiAnalysis.reasoning}</p>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground pt-1">
            <Sparkles className="size-3 text-ai" /> Last analysis 2 min ago · v4.2.1
          </div>
        </Card>
      </div>

      {/* Live positions + alerts */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card
          title="Live Positions"
          subtitle="Real-time unrealized performance"
          className="xl:col-span-2 p-4"
          action={
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              Total floating P&L <span className="text-profit font-bold">+${fmtNum(247.9, 2)}</span>
            </span>
          }
        >
          <div>
            {(data.livePositions || []).map((p) => (
              <PositionRow key={p.id} p={p} />
            ))}
          </div>
        </Card>

        <Card
          title="Recent Alerts"
          subtitle={`${data.alerts.filter((a) => a.unread).length} unread`}
          className="p-4"
          action={<Badge variant="secondary">{data.alerts.filter((a) => a.unread).length} new</Badge>}
        >
          <div className="divide-y divide-border/30">
            {data.alerts.slice(0, 5).map((a) => (
              <AlertRow key={a.id} a={a} />
            ))}
          </div>
        </Card>
      </div>

      {/* Distribution / weekly / sessions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Trade Distribution" subtitle="P&L per trade (R multiples)">
          <BarChartSimple data={data.tradeDistribution} height={200} />
        </Card>
        <Card title="Weekly Returns" subtitle="Rolling weekly performance">
          <BarChartSimple data={data.weeklyReturns} height={200} />
        </Card>
        <Card title="Session Analysis" subtitle="Performance by trading session">
          <div className="space-y-3 mt-1">
            {data.sessionAnalysis.map((s) => (
              <div key={s.label} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-foreground/90">{s.label}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {s.trades} trades ·{" "}
                    <span className={s.pnl >= 0 ? "text-profit" : "text-loss"}>
                      ${fmtNum(s.pnl, 0)}
                    </span>
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
      </div>

      {/* Patterns + pipeline + reviews */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card
          title="Patterns Currently Being Investigated"
          subtitle="Active AI research targets"
          className="xl:col-span-2"
          action={<Badge variant="secondary">{data.patterns.length} active</Badge>}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.patterns.map((p) => (
              <div key={p.id} className="rounded-lg bg-muted/20 border border-border/40 p-3 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-xs font-semibold">
                    <CircleDot className="size-3.5 text-ai" /> {p.name}
                  </span>
                  <Badge variant={p.status === "approved" ? "profit" : p.status === "investigating" ? "ai" : "outline"}>
                    {p.status}
                  </Badge>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">{p.detail}</p>
                <div className="flex items-center gap-2 pt-1">
                  <ProgressBar value={p.confidence} tone={p.confidence >= 75 ? "profit" : "ai"} />
                  <span className="text-[10px] text-muted-foreground w-9 text-right tabular-nums">{p.confidence}%</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Validation Pipeline" subtitle="Current strategy v4.2.1">
          <div className="space-y-3">
            {data.pipeline.map((step) => {
              const meta = pipelineMeta[step.status] ?? pipelineMeta.pending;
              const Icon = meta.icon;
              return (
                <div key={step.label} className="flex items-center gap-3">
                  <span className={`shrink-0 [&>svg]:size-3.5 ${meta.cls}`}>
                    <Icon />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium">{step.label}</span>
                      <span className="text-[10px] text-muted-foreground tabular-nums">
                        {step.status === "done" ? step.time : meta.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <ProgressBar value={step.progress} tone={step.status === "done" ? "profit" : step.status === "active" ? "ai" : "muted"} />
                      {step.confidence != null && (
                        <span className="text-[10px] text-muted-foreground w-9 text-right tabular-nums">
                          {step.confidence}%
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="rounded-lg bg-ai/5 border border-ai/20 p-3 space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Monte Carlo pass rate</span>
              <span className="font-semibold text-profit tabular-nums">{data.validation.passRate}%</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Walk-forward score</span>
              <span className="font-semibold tabular-nums">{data.validation.walkForwardScore}/100</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Overfitting risk</span>
              <Badge variant="profit">{data.validation.overfitRisk}</Badge>
            </div>
          </div>
        </Card>
      </div>

      {/* Recent AI reviews */}
      <Card title="Recent AI Reviews" subtitle="Trade-by-trade review with AI analysis">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {(data.reviews || []).slice(0, 6).map((r) => (
            <div key={r.id ?? r.version} className="rounded-lg bg-muted/20 border border-border/40 p-3 space-y-2 hover:bg-muted/30 transition-colors">
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold">
                  <FlaskConical className="size-3.5 text-ai" />
                  {r.version || r.strategy_version || "smc_crt"}
                </span>
                <Badge variant={r.status === "ACTIVE" || r.status === "active" ? "profit" : "outline"}>
                  {r.status || r.strategy_version || "reviewed"}
                </Badge>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-3">
                {r.summary || r.change_reason || r.ai_hypothesis || "AI review completed."}
              </p>
              <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                <span>{r.updated || r.created_at || "—"}</span>
                <span className="flex items-center gap-1 text-ai">
                  View <ChevronRight className="size-3" />
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </AppShell>
  );
}
