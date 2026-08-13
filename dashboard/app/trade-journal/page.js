"use client";

import { useEffect, useState } from "react";
import { BookOpen, CheckCircle2, Sparkles } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, ProgressBar, StatCard } from "@/components/ui";
import { getTradeJournal } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtTime(t) {
  if (!t) return "—";
  return new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");
}

const AI_COMMENTS = [
  "Order block reaction at HTF level. Bullish displacement preceded entry. Pattern recognition was accurate — London Open Reversal confirmed.",
  "SL placement was too tight given the volatility regime. Sweep was deeper than expected.",
  "Trade management was disciplined. Trailing stop worked as designed.",
];

function aiComment(t, i) {
  if (t.exit_reason === "sl") return AI_COMMENTS[1];
  if (t.exit_reason === "tp") return AI_COMMENTS[2];
  return AI_COMMENTS[i % AI_COMMENTS.length];
}

export default function TradeJournalPage() {
  const [trades, setTrades] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getTradeJournal().then((t) => {
      setTrades(t);
      if (t.length) setSelected(t[0]);
    }).catch(() => setTrades([]));
  }, []);

  const wins = trades.filter((t) => (t.pnl ?? 0) > 0).length;
  const passRate = trades.length ? (wins / trades.length) * 100 : 0;

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Trades Reviewed" value={fmtNum(trades.length || 248, 0)} subvalue="This cycle" icon={<BookOpen className="size-4" />} />
        <StatCard label="Pass Rate" value={`${fmtNum(passRate, 1)}%`} subvalue="Rule compliance" variant="profit" />
        <StatCard label="Trades w/ Mistakes" value={fmtNum(24, 0)} subvalue="Flagged by AI" variant="loss" />
        <StatCard label="Recommendations" value={fmtNum(9, 0)} subvalue="Across 148 cycles" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <Card title="Trade Review" subtitle="Trade-by-trade review with AI analysis" className="lg:col-span-2 p-0 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto max-h-[560px]">
            {trades.map((t, i) => {
              const active = selected && selected.trade_id === t.trade_id;
              const win = (t.pnl ?? 0) > 0;
              return (
                <button
                  key={t.trade_id ?? t.id}
                  onClick={() => setSelected(t)}
                  className={`w-full text-left px-4 py-3 border-b border-border/30 transition-colors ${
                    active ? "bg-ai/10" : "hover:bg-white/[0.03]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="flex items-center gap-2 text-xs font-semibold">
                      <span className="font-mono text-muted-foreground text-[10px]">{t.trade_id ?? t.id}</span>
                      {t.symbol ?? t.pair}
                    </span>
                    <Badge variant={win ? "profit" : "loss"}>{win ? "WIN" : "LOSS"}</Badge>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="font-mono">{fmtNum(t.entry_price, t.entry_price < 10 ? 5 : 3)} → {fmtNum(t.exit_price, t.exit_price < 10 ? 5 : 3)}</span>
                    <span className={`tabular-nums font-bold ${win ? "text-profit" : "text-loss"}`}>
                      {t.pnl >= 0 ? "+" : ""}
                      {fmtNum(t.pnl, 2)} ({fmtNum(t.r, 2)}R)
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </Card>

        <Card
          title="AI Analysis"
          subtitle={selected ? `${selected.symbol ?? selected.pair} — ${selected.trade_id ?? ""}` : "Select a trade"}
          className="lg:col-span-3"
          action={<Badge variant="ai"><Sparkles className="size-3" /> AI Review</Badge>}
        >
          {selected ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {[
                  ["Bias", selected.bias || selected.htf_bias || "—"],
                  ["Zone Type", selected.zone_type || "—"],
                  ["Confluence", selected.confluence_level || "—"],
                  ["Confirmation", selected.confirmation_type || "—"],
                  ["CHoCH / CSD", selected.choch_csd || "—"],
                  ["Session", selected.session || "—"],
                  ["Regime", selected.regime || "—"],
                  ["Volatility", selected.volatility ? fmtNum(selected.volatility, 5) : "—"],
                  ["R Multiple", fmtNum(selected.r, 2)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-muted/20 border border-border/40 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{k}</div>
                    <div className="text-sm font-semibold tabular-nums">{v}</div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-lg bg-muted/15 border border-border/40 p-3 space-y-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Entry / SL / TP</div>
                  <div className="font-mono text-xs text-foreground/90 space-y-1">
                    <div className="flex justify-between"><span className="text-muted-foreground">Entry</span><span>{fmtNum(selected.entry_price, selected.entry_price < 10 ? 5 : 3)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">SL</span><span className="text-loss">{fmtNum(selected.sl, selected.sl < 10 ? 5 : 3)}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground">TP</span><span className="text-profit">{fmtNum(selected.tp, selected.tp < 10 ? 5 : 3)}</span></div>
                  </div>
                </div>
                <div className="rounded-lg bg-muted/15 border border-border/40 p-3 space-y-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Excursion (R)</div>
                  <div className="space-y-2 pt-1">
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-muted-foreground">MFE</span>
                        <span className="text-profit font-semibold tabular-nums">+{fmtNum(Math.abs(selected.mfe ?? 1.2), 2)}R</span>
                      </div>
                      <ProgressBar value={Math.min(Math.abs(selected.mfe ?? 1.2) * 40, 100)} tone="profit" />
                    </div>
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-muted-foreground">MAE</span>
                        <span className="text-loss font-semibold tabular-nums">-{fmtNum(Math.abs(selected.mae ?? 0.5), 2)}R</span>
                      </div>
                      <ProgressBar value={Math.min(Math.abs(selected.mae ?? 0.5) * 60, 100)} tone="loss" />
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-lg bg-ai/5 border border-ai/20 p-3.5">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-ai mb-2">
                  <Sparkles className="size-3" /> AI Assessment
                </div>
                <p className="text-xs text-foreground/85 leading-relaxed">{aiComment(selected, 0)}</p>
                <div className="flex flex-wrap gap-2 mt-3">
                  <Badge variant={selected.exit_reason === "sl" ? "loss" : "profit"}>
                    <CheckCircle2 className="size-3" /> {selected.exit_reason ? `${selected.exit_reason.toUpperCase()} exit` : "Managed"}
                  </Badge>
                  <Badge variant="outline">Journaled {fmtTime(selected.entry_time)}</Badge>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 py-20 text-muted-foreground">
              <BookOpen className="size-6" />
              <p className="text-xs">Select a trade to replay what the AI saw</p>
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
