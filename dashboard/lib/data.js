// Dashboard data layer: fetches the FastAPI backend (proxied via /api) and
// normalizes into the shapes the UI consumes. No mock/demo data is used — every
// value comes from the integrated backend. When the backend is offline or has
// no data, the UI receives empty/default values and renders empty states.

export const INITIAL_CASH = 10000;

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getHealth() {
  try {
    return await fetchJSON("/api/health");
  } catch {
    return { status: "offline", service: "trading-bot" };
  }
}

export async function getDataRange(symbol = "XAUUSD", timeframe = "5m") {
  try {
    return await fetchJSON(`/api/data-range?symbol=${symbol}&timeframe=${timeframe}`);
  } catch {
    return { start: 0, end: 0, n_bars: 0 };
  }
}

export async function getModels() {
  try {
    const m = await fetchJSON("/api/models");
    return Array.isArray(m) ? m : [];
  } catch {
    return [];
  }
}

export async function saveModel(payload) {
  const r = await fetch("/api/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function deleteModel(id) {
  const r = await fetch(`/api/models/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function activateModel(id) {
  const r = await fetch(`/api/models/${id}/activate`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function testModel(id) {
  const r = await fetch(`/api/models/${id}/test`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function getMetrics() {
  try {
    const m = await fetchJSON("/api/metrics");
    return {
      online: true,
      winRate: m.win_rate ?? 0,
      profitFactor: m.profit_factor ?? 0,
      sharpe: m.sharpe_r ?? 0,
      sortino: m.sortino_r ?? 0,
      recoveryFactor: m.recovery_factor ?? 0,
      avgRR: m.expectancy_r ?? 0,
      expectancy: m.expectancy_r ?? 0,
      maxDrawdown: m.max_drawdown_pct ?? 0,
      netProfit: m.total_pnl ?? 0,
      totalTrades: m.n_trades ?? 0,
      largestWin: m.largest_win_currency ?? 0,
      largestLoss: m.largest_loss_currency ?? 0,
      avgWin: m.avg_win_r ?? 0,
      avgLoss: m.avg_loss_r ?? 0,
      maxConsecWins: m.max_r_streak ?? 0,
      maxConsecLosses: m.max_loss_streak ?? 0,
      totalReturnPct: m.total_return_pct ?? 0,
      finalEquity: m.final_equity ?? INITIAL_CASH,
      monthlyReturns: m.monthly_returns_pct ?? {},
      exitReasons: m.exit_reason_counts ?? {},
      raw: m,
    };
  } catch {
    return { online: false };
  }
}

export async function getTrades() {
  try {
    const t = await fetchJSON("/api/trades?limit=5000");
    return Array.isArray(t) ? t : [];
  } catch {
    return [];
  }
}

export async function getStrategies() {
  try {
    const s = await fetchJSON("/api/strategies");
    return Array.isArray(s) ? s : [];
  } catch {
    return [];
  }
}

export async function getReviews() {
  try {
    const r = await fetchJSON("/api/reviews?limit=100");
    return Array.isArray(r) ? r : [];
  } catch {
    return [];
  }
}

// Normalize the /api/live endpoint into the shape the Live Trades page uses.
export async function getLive() {
  try {
    const l = await fetchJSON("/api/live");
    if (!l || l.running === false) {
      return { online: false, running: false, detail: l?.detail || "not enabled", positions: [] };
    }
    const positions = (l.open_positions || []).map((p) => ({
      id: p.id,
      pair: p.symbol,
      direction: p.side === "buy" ? "LONG" : "SHORT",
      entryPrice: p.entry_price,
      currentPrice: p.current_price,
      sl: p.sl,
      tp: p.tp,
      lot: p.size,
      pnl: p.unrealized_pnl ?? 0,
      duration: p.open_time
        ? `${Math.max(1, Math.round((Date.now() / 1000 - p.open_time) / 60))}m`
        : "—",
    }));
    return {
      online: true,
      running: true,
      symbol: l.symbol,
      timeframe: l.timeframe,
      strategy: l.strategy,
      strategyVersion: l.strategy_version,
      status: l.status,
      detail: l.detail,
      balance: l.balance,
      equity: l.equity,
      realizedPnl: l.realized_pnl,
      lastPrice: l.last_price,
      nTrades: l.n_trades,
      nSignals: l.n_signals,
      nRejections: l.n_rejections,
      positions,
    };
  } catch {
    return { online: false, running: false, positions: [] };
  }
}

// Build an equity curve from trades: start at INITIAL_CASH, add each trade's
// net P/L in exit-time order.
export function equityFromTrades(trades, initial = INITIAL_CASH) {
  const sorted = [...trades].sort((a, b) => a.exit_time - b.exit_time);
  let eq = initial;
  const points = [{ t: 0, equity: eq }];
  for (const t of sorted) {
    eq += t.pnl ?? 0;
    points.push({ t: t.exit_time || t.entry_time, equity: Math.max(eq, 0) });
  }
  return points;
}

export function drawdownFromEquity(points) {
  let peak = -Infinity;
  return points.map((p) => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
    return { t: p.t, drawdown: Math.max(dd, 0) };
  });
}

export function fmtTime(t) {
  if (!t) return "—";
  return new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");
}

export async function getTradeHistory() {
  return getTrades();
}

export async function getTradeJournal() {
  const trades = await getTrades();
  return trades.slice(0, 24);
}

// ------------------------------------------------------------ real aggregations

function relativeTime(ts) {
  if (!ts) return "—";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function computeWeeklyReturns(trades) {
  const buckets = new Map();
  for (const t of trades) {
    if (!t.exit_time) continue;
    const d = new Date(t.exit_time * 1000);
    const key = `${d.getFullYear()}-W${Math.floor(d.getDate() / 7)}`;
    buckets.set(key, (buckets.get(key) || 0) + (t.pnl || 0));
  }
  return [...buckets.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .slice(-24)
    .map(([k, v], i) => ({ label: `W${i + 1}`, value: Number((v / 100).toFixed(1)) }));
}

function computeDailyReturns(trades) {
  const buckets = new Map();
  for (const t of trades) {
    if (!t.exit_time) continue;
    const d = new Date(t.exit_time * 1000);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    buckets.set(key, (buckets.get(key) || 0) + (t.pnl || 0));
  }
  return [...buckets.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .slice(-30)
    .map(([, v], i) => ({ label: String(i + 1), value: Number((v / 100).toFixed(1)) }));
}

function computeSessionAnalysis(trades) {
  const bySession = new Map();
  let totalPnl = 0;
  for (const t of trades) {
    const s = String(t.session || "Other");
    const b = bySession.get(s) || { n: 0, wins: 0, pnl: 0 };
    b.n += 1;
    b.pnl += t.pnl || 0;
    if ((t.pnl || 0) > 0) b.wins += 1;
    totalPnl += t.pnl || 0;
    bySession.set(s, b);
  }
  return [...bySession.entries()]
    .map(([label, b]) => ({
      label,
      trades: b.n,
      winRate: Number(((b.wins / b.n) * 100).toFixed(1)),
      pnl: b.pnl,
      avgPnl: Number((b.pnl / b.n).toFixed(1)),
      contribution: totalPnl ? Number(((b.pnl / totalPnl) * 100).toFixed(0)) : 0,
    }))
    .sort((a, b) => b.contribution - a.contribution);
}

function computePairDistribution(trades) {
  const bySym = new Map();
  for (const t of trades) {
    bySym.set(t.symbol, (bySym.get(t.symbol) || 0) + 1);
  }
  const rows = [...bySym.entries()].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count);
  if (rows.length <= 5) return rows;
  return rows.slice(0, 5).concat([{ label: "Others", count: rows.slice(5).reduce((a, b) => a + b.count, 0) }]);
}

function patternToCard(p, i) {
  return {
    id: p.id || `pat_${i}`,
    name: `${p.dimension || "segment"} ${p.value ?? ""}`.trim(),
    confidence: Math.round(p.win_rate || 0),
    status: p.direction === "outperform" ? "approved" : "investigating",
    detail: `n=${p.n ?? 0}, avg R ${p.avg_r ?? 0} — ${p.direction ?? "neutral"} segment`,
  };
}

// Build the AI Analysis panel from the latest real review.
function aiAnalysisFromReview(review) {
  if (!review) return null;
  const llmMatch = /^\[LLM:([^\]]+)\]/.exec(review.summary || "");
  return {
    confidence: null,
    model: llmMatch ? llmMatch[1] : "deterministic rules",
    reasoning: review.hypothesis || "No hypothesis recorded.",
    summary: review.summary || "",
    nTrades: review.n_trades || 0,
    compliance: review.rule_compliance || {},
    patterns: review.patterns || [],
    created_at: review.created_at || "",
  };
}

// Build an alert feed from real backend signals (reviews + health).
function buildAlerts(health, reviews) {
  const alerts = [];
  for (const r of reviews.slice(-8).reverse()) {
    alerts.push({
      id: r.id || `rev_${alerts.length}`,
      level: "ai",
      title: "AI review completed",
      time: relativeTime(r.created_at),
      unread: false,
      detail: r.summary || "Trade batch reviewed.",
    });
  }
  if (health?.status === "ok") {
    alerts.push({
      id: "sys-online",
      level: "success",
      title: "Backend online",
      time: "now",
      unread: false,
      detail: "API server is healthy and reachable.",
    });
  } else {
    alerts.push({
      id: "sys-offline",
      level: "warning",
      title: "Backend offline",
      time: "now",
      unread: true,
      detail: "The API server is unreachable — integrate and start it to see live data.",
    });
  }
  return alerts;
}

// Aggregate everything the Dashboard and derived pages need in one call.
// Only real backend data is returned; empty values when nothing exists yet.
export async function getDashboardData() {
  const [health, metrics, trades, strategies, reviews] = await Promise.all([
    getHealth(),
    getMetrics(),
    getTrades(),
    getStrategies(),
    getReviews(),
  ]);

  const hasData = metrics.online && metrics.totalTrades > 0;
  const equityPoints = hasData ? equityFromTrades(trades) : [];
  const drawdownPoints = drawdownFromEquity(equityPoints);

  const cards = hasData
    ? {
        equity: metrics.finalEquity,
        todayPnL: metrics.netProfit,
        todayPnLPct: metrics.totalReturnPct,
        winRate: metrics.winRate,
        maxDrawdown: -Math.abs(metrics.maxDrawdown),
        sharpeRatio: metrics.sharpe,
        profitFactor: metrics.profitFactor,
        aiConfidence: 0,
      }
    : {
        equity: 0,
        todayPnL: 0,
        todayPnLPct: 0,
        winRate: 0,
        maxDrawdown: 0,
        sharpeRatio: 0,
        profitFactor: 0,
        aiConfidence: 0,
      };

  const recent = [...trades].sort((a, b) => b.entry_time - a.entry_time).slice(0, 8);
  const livePositions = hasData
    ? recent.map((t) => ({
        id: t.trade_id,
        pair: t.symbol,
        direction: String(t.side).toUpperCase(),
        entryPrice: t.entry_price,
        currentPrice: t.exit_price,
        sl: t.sl,
        tp: t.tp,
        lot: t.size,
        pnl: t.pnl,
        pnlPct: t.entry_price ? (t.pnl / t.entry_price) * 100 : 0,
        openTime: fmtTime(t.entry_time),
        duration: `${Math.round((t.duration_seconds || 0) / 60)}m`,
        risk: 1,
      }))
    : [];

  const latestReview = reviews.length ? reviews[reviews.length - 1] : null;

  return {
    health,
    hasData,
    cards,
    equityPoints,
    drawdownPoints,
    returnPct: hasData ? metrics.totalReturnPct : 0,
    aiAnalysis: aiAnalysisFromReview(latestReview),
    livePositions,
    alerts: buildAlerts(health, reviews),
    tradeDistribution: hasData
      ? trades.map((t, i) => ({ label: String(i + 1), value: t.r })).slice(0, 30)
      : [],
    weeklyReturns: hasData ? computeWeeklyReturns(trades) : [],
    dailyReturns: hasData ? computeDailyReturns(trades) : [],
    sessionAnalysis: hasData ? computeSessionAnalysis(trades) : [],
    pairs: hasData ? computePairDistribution(trades) : [],
    patterns: latestReview ? (latestReview.patterns || []).map(patternToCard) : [],
    latestReview,
    strategies,
    reviews,
    trades,
    metrics,
  };
}
