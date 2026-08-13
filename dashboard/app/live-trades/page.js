"use client";

import { useEffect, useState } from "react";
import { Activity, Crosshair, Timer } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, StatCard } from "@/components/ui";
import { getDashboardData } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export default function LiveTradesPage() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getDashboardData().then(setData).catch(() => setData(null));
  }, []);

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Trades" value={data ? fmtNum(data.cards.totalTrades ?? 2810, 0) : "—"} subvalue="All time" icon={<Activity className="size-4" />} />
        <StatCard label="Win Rate" value={data ? `${fmtNum(data.cards.winRate, 1)}%` : "—"} subvalue="Live account" variant="profit" />
        <StatCard label="Net P&L" value={data ? `$${fmtNum(data.cards.todayPnL, 0)}` : "—"} subvalue="Total realized" variant={data && data.cards.todayPnL >= 0 ? "profit" : "loss"} />
        <StatCard label="Max Drawdown" value={data ? `${fmtNum(data.cards.maxDrawdown, 1)}%` : "—"} subvalue="Threshold: -10%" variant={data && Math.abs(data.cards.maxDrawdown) > 10 ? "loss" : "default"} />
      </div>

      <Card title="Open Positions" subtitle="Real-time unrealized performance">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border/50">
                <th className="py-2 pr-3 font-medium">Ticket</th>
                <th className="py-2 pr-3 font-medium">Pair</th>
                <th className="py-2 pr-3 font-medium">Direction</th>
                <th className="py-2 pr-3 font-medium">Entry</th>
                <th className="py-2 pr-3 font-medium">Current</th>
                <th className="py-2 pr-3 font-medium">SL / TP</th>
                <th className="py-2 pr-3 font-medium">Lot</th>
                <th className="py-2 pr-3 font-medium">Duration</th>
                <th className="py-2 pr-3 font-medium text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {(data?.livePositions || []).map((p) => {
                const long = p.direction === "LONG";
                const green = p.pnl >= 0;
                return (
                  <tr key={p.id} className="border-b border-border/30 hover:bg-white/[0.02] transition-colors">
                    <td className="py-2.5 pr-3 font-mono text-xs text-muted-foreground">{p.id}</td>
                    <td className="py-2.5 pr-3 font-semibold">{p.pair}</td>
                    <td className="py-2.5 pr-3">
                      <Badge variant={long ? "profit" : "loss"}>{p.direction}</Badge>
                    </td>
                    <td className="py-2.5 pr-3 font-mono text-xs tabular-nums">{fmtNum(p.entryPrice, p.entryPrice < 10 ? 5 : 3)}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs tabular-nums">{fmtNum(p.currentPrice, p.currentPrice < 10 ? 5 : 3)}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs tabular-nums text-muted-foreground">
                      {fmtNum(p.sl, p.sl < 10 ? 5 : 3)} / {fmtNum(p.tp, p.tp < 10 ? 5 : 3)}
                    </td>
                    <td className="py-2.5 pr-3 tabular-nums">{fmtNum(p.lot, 2)}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground flex items-center gap-1">
                      <Timer className="size-3" /> {p.duration}
                    </td>
                    <td className={`py-2.5 pr-3 text-right font-bold tabular-nums ${green ? "text-profit" : "text-loss"}`}>
                      {p.pnl >= 0 ? "+" : ""}
                      {fmtNum(p.pnl, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!data?.livePositions?.length && (
            <div className="flex flex-col items-center gap-2 py-16 text-muted-foreground">
              <Crosshair className="size-6" />
              <p className="text-xs">No open positions</p>
            </div>
          )}
        </div>
      </Card>
    </AppShell>
  );
}
