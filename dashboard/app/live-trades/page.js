"use client";

import { useEffect, useState } from "react";
import { Activity, Crosshair, RefreshCw, Timer } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, StatCard } from "@/components/ui";
import { getLive } from "@/lib/data";

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

const POLL_MS = 10000;

export default function LiveTradesPage() {
  const [live, setLive] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const l = await getLive();
      if (!cancelled) setLive(l);
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const online = live?.online;
  const positions = online ? live.positions : [];
  const statusTone =
    live?.status === "down" ? "loss" : live?.status === "warn" ? "warn" : "profit";

  return (
    <AppShell>
      <Card title="Live Pipeline" subtitle="Paper-trading engine state (never real money)">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          {online ? (
            <>
              <Badge variant={statusTone}>{live.status.toUpperCase()}</Badge>
              <span className="text-muted-foreground">
                <span className="font-semibold text-foreground">{live.symbol}</span>{" "}
                {live.timeframe} · {live.strategy} v{live.strategyVersion || "?"}
              </span>
              <span className="text-muted-foreground">
                Balance <span className="font-mono tabular-nums text-foreground">${fmtNum(live.balance, 2)}</span>
              </span>
              <span className="text-muted-foreground">
                Equity <span className="font-mono tabular-nums text-foreground">${fmtNum(live.equity, 2)}</span>
              </span>
              <span className="text-muted-foreground">
                Realized{" "}
                <span className={`font-mono tabular-nums ${live.realizedPnl >= 0 ? "text-profit" : "text-loss"}`}>
                  {live.realizedPnl >= 0 ? "+" : ""}${fmtNum(live.realizedPnl, 2)}
                </span>
              </span>
              <span className="text-muted-foreground">Last bar {fmtNum(live.lastPrice, live.lastPrice < 10 ? 5 : 3)}</span>
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <RefreshCw className="size-3 animate-spin" /> auto-refresh {POLL_MS / 1000}s
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">
              Live pipeline not running — start the server with <code className="font-mono text-xs">--live</code>.
              {live?.detail ? ` (${live.detail})` : ""}
            </span>
          )}
        </div>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Trades" value={online ? fmtNum(live.nTrades, 0) : "—"} subvalue="All time" icon={<Activity className="size-4" />} />
        <StatCard label="Signals" value={online ? fmtNum(live.nSignals, 0) : "—"} subvalue="Generated" />
        <StatCard label="Net P&L" value={online ? `${live.realizedPnl >= 0 ? "+" : ""}$${fmtNum(live.realizedPnl, 0)}` : "—"} subvalue={online ? "Realized" : "Not running"} variant={(online ? live.realizedPnl : 0) >= 0 ? "profit" : "loss"} />
        <StatCard label="Pipeline" value={online ? live.status.toUpperCase() : "OFF"} subvalue={online ? live.detail : "not running"} variant={statusTone} />
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
              {positions.map((p) => {
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
          {!positions.length && (
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
