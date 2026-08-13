"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, GitBranch, Sparkles } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { DEMO, getStrategies } from "@/lib/data";

function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

const STATUS_VARIANT = {
  ACTIVE: "active",
  active: "active",
  rejected: "loss",
  replaced: "outline",
  validating: "ai",
  hypothesis: "outline",
};

const DETAILS = {
  "v4.3.1-beta": {
    changes: ["Added RSI divergence filter", "Tightened ATR-based SL", "Improved trend strength threshold"],
    reason: "Detected 34 false trend entries in London session. RSI divergence filter added to reduce whipsaws.",
    patterns: ["London Open Reversal", "RSI Double Divergence", "EMA Cross"],
  },
};

export default function StrategyVersionsPage() {
  const [versions, setVersions] = useState([]);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    getStrategies().then((s) => setVersions(s.length ? s : DEMO.strategyHistory)).catch(() => setVersions(DEMO.strategyHistory));
  }, []);

  const active = versions.filter((v) => v.status === "ACTIVE" || v.status === "active").length;
  const rejected = versions.filter((v) => v.status === "rejected").length;

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Versions" value={fmtNum(versions.length || 4, 0)} subvalue="All time" icon={<GitBranch className="size-4" />} />
        <StatCard label="Active" value={fmtNum(active || 1, 0)} subvalue="In production" variant="profit" />
        <StatCard label="Rejected" value={fmtNum(rejected, 0)} subvalue="Kept for reference" variant="loss" />
        <StatCard label="Changes" value={fmtNum(versions.reduce((s, v) => s + (v.changes ?? 0), 0) || 7, 0)} subvalue="Across versions" />
      </div>

      <Card title="Strategy Versions" subtitle="Version history and comparison">
        <div className="space-y-2">
          {versions.map((v) => {
            const variant = STATUS_VARIANT[v.status] ?? "outline";
            const open = expanded === (v.version ?? v.id);
            const detail = DETAILS[v.version];
            return (
              <div key={v.version ?? v.id} className="rounded-lg bg-muted/20 border border-border/40 overflow-hidden">
                <button
                  onClick={() => setExpanded(open ? null : v.version ?? v.id)}
                  className="w-full flex items-center gap-3 p-3 text-left hover:bg-muted/30 transition-colors"
                >
                  <div className="flex-1 min-w-0 flex items-center gap-3">
                    <div className="flex flex-col">
                      <span className="text-sm font-bold tabular-nums">{v.version}</span>
                      <span className="text-[10px] text-muted-foreground">{v.name ?? "smc_crt"} · {v.updated ?? v.created_at ?? "—"}</span>
                    </div>
                  </div>
                  <span className="hidden md:inline text-[11px] text-muted-foreground tabular-nums">
                    {v.changes ?? v.test_results?.n_changes ?? 0} changes
                  </span>
                  <div className="w-24 hidden lg:block">
                    <ProgressBar value={v.score ?? v.test_results?.score ?? 0} tone={(v.score ?? 0) >= 80 ? "profit" : "ai"} />
                  </div>
                  <Badge variant={variant}>{String(v.status).toUpperCase()}</Badge>
                  <ChevronDown className={`size-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
                </button>
                {open && (
                  <div className="px-3 pb-3 space-y-3 border-t border-border/40 pt-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-ai mb-1 flex items-center gap-1">
                        <Sparkles className="size-3" /> Reason created
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">{detail?.reason ?? v.change_reason ?? v.ai_hypothesis ?? "No reason recorded."}</p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Changes</div>
                        <div className="space-y-1">
                          {(detail?.changes ?? (Array.isArray(v.changes) ? v.changes : [])).map((c, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs text-foreground/85">
                              <CheckCircle2 className="size-3.5 text-profit" /> {c}
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Patterns used</div>
                        <div className="flex flex-wrap gap-1.5">
                          {(detail?.patterns ?? []).map((p, i) => (
                            <Badge key={i} variant="outline">{p}</Badge>
                          ))}
                          {!detail?.patterns?.length && <span className="text-xs text-muted-foreground">—</span>}
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        ["Backtest", v.backtestScore ?? 87, "ai"],
                        ["Monte Carlo", v.monteCarloScore ?? 82, "ai"],
                        ["Walk Forward", v.walkForwardScore ?? 78, "ai"],
                      ].map(([k, val, tone]) => (
                        <div key={k} className="rounded-md bg-muted/10 border border-border/40 p-2">
                          <div className="text-[10px] text-muted-foreground mb-1">{k}</div>
                          <div className="flex items-center gap-2">
                            <ProgressBar value={val} tone={tone} />
                            <span className="text-[10px] tabular-nums text-foreground/80 w-6 text-right">{val}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </AppShell>
  );
}
