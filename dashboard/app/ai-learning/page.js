"use client";

import { useEffect, useState } from "react";
import { BookOpen, BrainCircuit, Database, Sparkles, Zap } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { TrendLineChart } from "@/components/charts";
import { DEMO } from "@/lib/data";

const knowledge = [
  { id: "KB-01", title: "RSI divergence confirms trend continuation 79% of time", confidence: 79, cycles: 148 },
  { id: "KB-02", title: "Liquidity sweep below previous low precedes 78% of losing trades", confidence: 78, cycles: 120 },
  { id: "KB-03", title: "London Open patterns remain highly reliable", confidence: 92, cycles: 148 },
  { id: "KB-04", title: "NY overlap causes more fakeouts", confidence: 64, cycles: 96 },
  { id: "KB-05", title: "OB confirmation stronger after displacement", confidence: 86, cycles: 112 },
];

export default function AILearningPage() {
  const [show, setShow] = useState(false);
  useEffect(() => setShow(true), []);
  const l = DEMO.learning;

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Learning Cycle" value={fmtNum(l.cycle, 0)} subvalue={l.status} icon={<BrainCircuit className="size-4" />} variant="ai" />
        <StatCard label="Trades Reviewed" value={fmtNum(l.tradesReviewed, 0)} subvalue={l.dataset} />
        <StatCard label="Learning Speed" value={l.speed} subvalue="Throughput" variant="profit" />
        <StatCard label="Current Strategy" value={l.currentStrategy} subvalue={`Last learning: ${l.lastLearning}`} icon={<Sparkles className="size-4" />} variant="ai" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Learning Accuracy Trend" subtitle="Recommendation accuracy across cycles" className="lg:col-span-2">
          <TrendLineChart data={l.accuracyTrend} height={240} />
          <div className="rounded-lg bg-ai/5 border border-ai/20 p-3 flex items-start gap-2.5 mt-2">
            <Sparkles className="size-4 text-ai shrink-0 mt-0.5" />
            <p className="text-xs text-muted-foreground leading-relaxed">
              The AI reviews each trade batch deterministically, extracts segment patterns, and builds evidence-based
              hypotheses. Accuracy is computed against whether recommended changes survive validation.
            </p>
          </div>
        </Card>

        <Card title="Learning Pipeline" subtitle="Live status" className="p-5">
          <div className="space-y-3">
            {[
              { icon: Database, label: "Model", value: l.modelVersion },
              { icon: BrainCircuit, label: "Patterns Discovered", value: `${l.patternsDiscovered}` },
              { icon: Zap, label: "Strategies Generated", value: `${l.strategiesGenerated}` },
              { icon: Sparkles, label: "Pattern Confidence", value: `${l.patternConfidence}%` },
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
            <span className="size-2 rounded-full bg-ai animate-pulse-slow" /> Learning cycle in progress
          </div>
        </Card>
      </div>

      <Card title="Knowledge Base" subtitle="Patterns Currently Being Investigated" action={<Badge variant="secondary">{knowledge.length} entries</Badge>}>
        <div className="space-y-2">
          {knowledge.map((k) => (
            <div key={k.id} className="flex items-center gap-3 rounded-lg bg-muted/20 border border-border/40 p-3 hover:bg-muted/30 transition-colors">
              <span className="font-mono text-[10px] text-muted-foreground shrink-0">{k.id}</span>
              <BookOpen className="size-4 text-ai shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate">{k.title}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">Validated across {k.cycles} cycles</p>
              </div>
              <div className="w-32 shrink-0 hidden sm:block">
                <ProgressBar value={k.confidence} tone={k.confidence >= 75 ? "profit" : "ai"} />
              </div>
              <span className="text-xs font-semibold tabular-nums text-profit w-10 text-right shrink-0">{k.confidence}%</span>
            </div>
          ))}
        </div>
      </Card>
    </AppShell>
  );
}

function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}
