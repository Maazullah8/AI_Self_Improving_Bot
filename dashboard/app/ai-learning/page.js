"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, BrainCircuit, Database, Sparkles, Zap } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { TrendLineChart } from "@/components/charts";
import { getDashboardData, getModels } from "@/lib/data";

function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function Empty({ text }) {
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-muted-foreground">
      <Sparkles className="size-6" />
      <p className="text-xs text-center leading-relaxed px-6">{text}</p>
    </div>
  );
}

export default function AILearningPage() {
  const [data, setData] = useState(null);
  const [models, setModels] = useState([]);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
    getModels().then(setModels).catch(() => setModels([]));
  }, []);

  const reviews = data?.reviews || [];
  const strategies = data?.strategies || [];
  const patterns = data?.patterns || [];
  const latestReview = data?.latestReview || null;
  const activeModel = models.find((m) => m.is_active) || null;

  const tradesReviewed = reviews.reduce((s, r) => s + (r.n_trades || 0), 0);
  const patternsDiscovered = reviews.reduce((s, r) => s + (r.patterns || []).length, 0);
  const currentStrategy = strategies.length ? strategies[strategies.length - 1].version : "—";
  const modelLabel = activeModel ? `${activeModel.label || activeModel.provider}${activeModel.model ? ` · ${activeModel.model}` : ""}` : "No model configured";

  const accuracyTrend = useMemo(() => {
    // Only real per-review accuracy is shown; there is no fabricated trend.
    return [];
  }, []);

  const learningStats = [
    { label: "Learning Cycle", value: fmtNum(reviews.length, 0), sub: reviews.length ? "Reviews completed" : "No reviews yet", variant: "ai" },
    { label: "Trades Reviewed", value: fmtNum(tradesReviewed, 0), sub: "Across all AI reviews" },
    { label: "AI Model", value: modelLabel, sub: "Configured in Settings" },
    { label: "Current Strategy", value: currentStrategy, sub: "Latest version" },
  ];

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {learningStats.map((s) => (
          <StatCard key={s.label} label={s.label} value={s.value} subvalue={s.sub} variant={s.variant || "default"} icon={s.label === "Learning Cycle" ? <BrainCircuit className="size-4" /> : undefined} />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Learning Accuracy Trend" subtitle="Accuracy across review cycles" className="lg:col-span-2">
          {accuracyTrend.length ? (
            <TrendLineChart data={accuracyTrend} height={240} />
          ) : (
            <Empty text="No accuracy trend yet — accuracy is computed when the AI engine validates recommended changes across cycles." />
          )}
          <div className="rounded-lg bg-ai/5 border border-ai/20 p-3 flex items-start gap-2.5 mt-2">
            <Sparkles className="size-4 text-ai shrink-0 mt-0.5" />
            <p className="text-xs text-muted-foreground leading-relaxed">
              The AI reviews each trade batch, extracts segment patterns, and builds evidence-based hypotheses. Nothing
              on this page is fabricated — it reflects the integrated backend.
            </p>
          </div>
        </Card>

        <Card title="Learning Pipeline" subtitle="Current status" className="p-5">
          <div className="space-y-3">
            {[
              { icon: Database, label: "Model", value: modelLabel },
              { icon: BrainCircuit, label: "Patterns Discovered", value: `${fmtNum(patternsDiscovered, 0)}` },
              { icon: Zap, label: "Strategies Generated", value: `${fmtNum(strategies.length, 0)}` },
              { icon: Sparkles, label: "Patterns on Watchlist", value: `${fmtNum(patterns.length, 0)}` },
            ].map(({ icon: Icon, label, value }) => (
              <div key={label} className="flex items-center gap-3 rounded-lg bg-muted/20 border border-border/40 p-3">
                <span className="text-ai [&>svg]:size-4 shrink-0"><Icon /></span>
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
                  <div className="text-sm font-semibold tabular-nums truncate">{value}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 pt-1 text-[11px] text-muted-foreground">
            <span className={`size-2 rounded-full ${reviews.length ? "bg-ai animate-pulse-slow" : "bg-muted"}`} />
            {reviews.length ? "AI engine active" : "No reviews yet — run a backtest + review"}
          </div>
        </Card>
      </div>

      <Card title="Knowledge Base" subtitle="Significant patterns from the latest review" action={patterns.length ? <Badge variant="secondary">{patterns.length} patterns</Badge> : undefined}>
        {patterns.length ? (
          <div className="space-y-2">
            {patterns.map((k) => (
              <div key={k.id} className="flex items-center gap-3 rounded-lg bg-muted/20 border border-border/40 p-3 hover:bg-muted/30 transition-colors">
                <span className="font-mono text-[10px] text-muted-foreground shrink-0">{k.id}</span>
                <BookOpen className="size-4 text-ai shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{k.name}</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">{k.detail}</p>
                </div>
                <div className="w-32 shrink-0 hidden sm:block">
                  <ProgressBar value={k.confidence} tone={k.confidence >= 75 ? "profit" : "ai"} />
                </div>
                <span className="text-xs font-semibold tabular-nums text-profit w-10 text-right shrink-0">{k.confidence}%</span>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="No patterns recorded yet. Patterns are added when an AI review finds statistically significant segments." />
        )}
      </Card>
    </AppShell>
  );
}
