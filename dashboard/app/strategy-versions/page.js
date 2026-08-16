"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, GitBranch, Sparkles } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { getStrategies } from "@/lib/data";

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

export default function StrategyVersionsPage() {
  const [versions, setVersions] = useState(null);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    getStrategies().then(setVersions).catch(() => setVersions([]));
  }, []);

  if (versions === null) {
    return (
      <AppShell>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card-elevated p-4 h-[96px] animate-pulse" />
          ))}
        </div>
        <div className="card-elevated p-5 h-[200px] animate-pulse" />
      </AppShell>
    );
  }

  const active = versions.filter((v) => v.status === "ACTIVE" || v.status === "active").length;
  const rejected = versions.filter((v) => v.status === "rejected").length;
  const changes = versions.reduce((s, v) => s + (v.changes ?? 0), 0);

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Versions" value={fmtNum(versions.length, 0)} subvalue="All time" icon={<GitBranch className="size-4" />} />
        <StatCard label="Active" value={fmtNum(active, 0)} subvalue="In production" variant="profit" />
        <StatCard label="Rejected" value={fmtNum(rejected, 0)} subvalue="Kept for reference" variant="loss" />
        <StatCard label="Changes" value={fmtNum(changes, 0)} subvalue="Across versions" />
      </div>

      <Card title="Strategy Versions" subtitle="Version history and comparison">
        {versions.length ? (
          <div className="space-y-2">
            {versions.map((v) => {
              const variant = STATUS_VARIANT[v.status] ?? "outline";
              const open = expanded === (v.version ?? v.id);
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
                        <p className="text-xs text-muted-foreground leading-relaxed">{v.change_reason ?? v.ai_hypothesis ?? "No reason recorded."}</p>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Changes</div>
                          <div className="space-y-1">
                            {(Array.isArray(v.changes) ? v.changes : []).map((c, i) => (
                              <div key={i} className="flex items-center gap-2 text-xs text-foreground/85">
                                <CheckCircle2 className="size-3.5 text-profit" /> {c}
                              </div>
                            ))}
                            {!Array.isArray(v.changes) && <span className="text-xs text-muted-foreground">—</span>}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Patterns used</div>
                          <div className="flex flex-wrap gap-1.5">
                            {Array.isArray(v.rules) && v.rules.map((r, i) => (
                              <Badge key={i} variant="outline">{r}</Badge>
                            ))}
                            {!Array.isArray(v.rules)?.length && <span className="text-xs text-muted-foreground">—</span>}
                          </div>
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          ["Backtest", v.test_results?.score ?? null],
                          ["Monte Carlo", v.test_results?.monte_carlo_pass_rate ?? null],
                          ["Walk Forward", v.test_results?.walk_forward_score ?? null],
                        ].map(([k, val]) => (
                          <div key={k} className="rounded-md bg-muted/10 border border-border/40 p-2">
                            <div className="text-[10px] text-muted-foreground mb-1">{k}</div>
                            {val != null ? (
                              <div className="flex items-center gap-2">
                                <ProgressBar value={val} tone="ai" />
                                <span className="text-[10px] tabular-nums text-foreground/80 w-6 text-right">{val}</span>
                              </div>
                            ) : (
                              <span className="text-[10px] text-muted-foreground">—</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="py-16 text-center text-xs text-muted-foreground">
            No strategy versions yet. Promote a candidate through validation to see it here.
          </div>
        )}
      </Card>
    </AppShell>
  );
}
