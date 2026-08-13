"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, History, Search } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge, Card, StatCard } from "@/components/ui";
import { getTradeHistory } from "@/lib/data";

const PAGE_SIZE = 15;

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtTime(t) {
  if (!t) return "—";
  const d = new Date(t * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ");
}

function sideLabel(side) {
  return String(side).toUpperCase() === "SELL" ? "SELL" : "LONG";
}

export default function TradeHistoryPage() {
  const [trades, setTrades] = useState([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("ALL");
  const [page, setPage] = useState(1);

  useEffect(() => {
    getTradeHistory().then(setTrades).catch(() => setTrades([]));
  }, []);

  const filtered = useMemo(() => {
    return trades.filter((t) => {
      const q = query.toLowerCase();
      const symbol = (t.symbol || t.pair || "").toLowerCase();
      const id = (t.trade_id || "").toLowerCase();
      const matchQ = !q || symbol.includes(q) || id.includes(q);
      const win = (t.pnl ?? 0) > 0;
      const matchR = result === "ALL" || (result === "WIN" && win) || (result === "LOSS" && !win);
      return matchQ && matchR;
    });
  }, [trades, query, result]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const rows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const wins = filtered.filter((t) => (t.pnl ?? 0) > 0).length;
  const netPnl = filtered.reduce((s, t) => s + (t.pnl ?? 0), 0);

  return (
    <AppShell>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Trades" value={fmtNum(trades.length, 0)} subvalue="All time" icon={<History className="size-4" />} />
        <StatCard label="Win Rate" value={trades.length ? `${((wins / trades.length) * 100).toFixed(1)}%` : "—"} subvalue="Filtered" variant="profit" />
        <StatCard label="Net P&L" value={`$${fmtNum(netPnl, 0)}`} subvalue="Filtered result" variant={netPnl >= 0 ? "profit" : "loss"} />
        <StatCard label="Avg Trade" value={`$${trades.length ? fmtNum(netPnl / trades.length, 2) : "—"}`} subvalue="Per trade" />
      </div>

      <Card title="Trade History" subtitle="Full journal of executed trades">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
              placeholder="Search by pair or ID..."
              className="w-full bg-muted/30 border border-border rounded-md pl-9 pr-3 py-2 text-xs placeholder:text-muted-foreground focus:outline-none focus:border-ai/50 focus:ring-1 focus:ring-ai/30"
            />
          </div>
          {["ALL", "WIN", "LOSS"].map((r) => (
            <button
              key={r}
              onClick={() => {
                setResult(r);
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                result === r
                  ? "bg-ai/20 text-ai border-ai/30"
                  : "bg-muted/30 text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border/50">
                <th className="py-2 pr-3 font-medium">ID</th>
                <th className="py-2 pr-3 font-medium">Pair</th>
                <th className="py-2 pr-3 font-medium">Side</th>
                <th className="py-2 pr-3 font-medium">Entry Time</th>
                <th className="py-2 pr-3 font-medium">Entry → Exit</th>
                <th className="py-2 pr-3 font-medium">Exit</th>
                <th className="py-2 pr-3 font-medium">R</th>
                <th className="py-2 pr-3 font-medium">Zone</th>
                <th className="py-2 pr-3 font-medium">Conf</th>
                <th className="py-2 pr-3 font-medium text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const long = sideLabel(t.side) === "LONG";
                const pnl = t.pnl ?? 0;
                const green = pnl > 0;
                return (
                  <tr key={t.trade_id ?? t.id} className="border-b border-border/30 hover:bg-white/[0.02] transition-colors">
                    <td className="py-2.5 pr-3 font-mono text-xs text-muted-foreground">{t.trade_id ?? t.id}</td>
                    <td className="py-2.5 pr-3 font-semibold">{t.symbol ?? t.pair}</td>
                    <td className="py-2.5 pr-3">
                      <Badge variant={long ? "profit" : "loss"}>{sideLabel(t.side)}</Badge>
                    </td>
                    <td className="py-2.5 pr-3 text-xs font-mono text-muted-foreground tabular-nums">{fmtTime(t.entry_time)}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs tabular-nums">
                      {fmtNum(t.entry_price, t.entry_price < 10 ? 5 : 3)} → {fmtNum(t.exit_price, t.exit_price < 10 ? 5 : 3)}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge variant={t.exit_reason === "tp" ? "profit" : t.exit_reason === "sl" ? "loss" : "outline"}>
                        {(t.exit_reason || "exit").toUpperCase()}
                      </Badge>
                    </td>
                    <td className={`py-2.5 pr-3 font-bold tabular-nums ${t.r >= 0 ? "text-profit" : "text-loss"}`}>{fmtNum(t.r, 2)}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground">{t.zone_type || "—"}</td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground">{t.confluence_level || "—"}</td>
                    <td className={`py-2.5 pr-3 text-right font-bold tabular-nums ${green ? "text-profit" : "text-loss"}`}>
                      {pnl >= 0 ? "+" : ""}
                      {fmtNum(pnl, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!rows.length && (
            <div className="py-16 text-center text-xs text-muted-foreground">No trades match your filters.</div>
          )}
        </div>

        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-muted-foreground tabular-nums">
            Showing {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={safePage <= 1}
              className="p-1.5 rounded-md border border-border bg-muted/20 text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="text-xs text-muted-foreground tabular-nums px-2">
              {safePage} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={safePage >= totalPages}
              className="p-1.5 rounded-md border border-border bg-muted/20 text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      </Card>
    </AppShell>
  );
}
