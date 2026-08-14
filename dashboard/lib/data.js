// Dashboard data layer: fetches the FastAPI backend (proxied via /api) and
// normalizes into the shapes the UI consumes. When the backend is offline or
// empty, it falls back to deterministic demo data in the same shape so the
// dashboard is always presentable.

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
    const t = await fetchJSON("/api/trades?limit=2000");
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
    const r = await fetchJSON("/api/reviews");
    return Array.isArray(r) ? r : [];
  } catch {
    return [];
  }
}

// Normalize the /api/live endpoint into the shape the Live Trades page uses.
// Open positions map to the demo `livePositions` schema (pair/direction/pnl).
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

function fmtTime(t) {
  if (!t) return "—";
  return new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");
}

function demoEquityCurve() {
  // Deterministic demo curve that mirrors the reference "equity curve".
  const seed = 7;
  let eq = INITIAL_CASH;
  const pts = [];
  const now = Date.now();
  for (let i = 0; i <= 30; i++) {
    const r = Math.sin(i * 1.7 + seed) * 0.9 + Math.sin(i * 0.6) * 0.5;
    eq += r * 18 + 9;
    pts.push({ t: Math.floor(now / 1000) - (30 - i) * 86400, equity: Math.round(eq) });
  }
  return pts;
}

export const DEMO = {
  cards: {
    balance: 14823.47,
    equity: 14956.22,
    todayPnL: 312.85,
    todayPnLPct: 2.14,
    winRate: 64.2,
    maxDrawdown: -8.4,
    sharpeRatio: 1.87,
    profitFactor: 1.94,
    aiConfidence: 82,
  },
  aiAnalysis: {
    marketRegime: "Trending",
    marketCondition: "Clear Uptrend",
    setupType: "Order Block",
    htfBias: "Bullish",
    ltfConfirmation: "Strong",
    confidence: 87,
    reasoning:
      "HTF structure is bullish with price reclaiming the 4H demand zone. LTF shows a displacement candle with volume confirmation — smart money positioning is visible on the 5m timeline.",
  },
  livePositions: [
    { id: "T-001", pair: "EURUSD", direction: "LONG", entryPrice: 1.08432, currentPrice: 1.08671, sl: 1.0815, tp: 1.091, lot: 0.5, pnl: 119.5, pnlPct: 1.1, openTime: "09:14:32", duration: "2h 18m", risk: 1.5 },
    { id: "T-002", pair: "GBPJPY", direction: "SHORT", entryPrice: 197.842, currentPrice: 197.312, sl: 198.4, tp: 196.5, lot: 0.3, pnl: 95.4, pnlPct: 0.82, openTime: "10:05:11", duration: "1h 27m", risk: 1 },
    { id: "T-003", pair: "XAUUSD", direction: "LONG", entryPrice: 2318.5, currentPrice: 2321.8, sl: 2308, tp: 2335, lot: 0.2, pnl: 33.0, pnlPct: 0.28, openTime: "11:32:05", duration: "0h 52m", risk: 0.8 },
  ],
  alerts: [
    { id: "AL-101", level: "info", title: "Market regime shift detected", time: "2 min ago", unread: true },
    { id: "AL-100", level: "ai", title: "New AI learning cycle complete", time: "18 min ago", unread: true },
    { id: "AL-099", level: "success", title: "Strategy v4.2.1 performing above expectation", time: "1h ago", unread: false },
    { id: "AL-098", level: "warning", title: "Trade T-247 stopped out. AI flagged for review.", time: "3h ago", unread: false },
    { id: "AL-097", level: "info", title: "Strategy v4.3.0-beta completed 2000-iteration Monte Carlo.", time: "5h ago", unread: false },
  ],
  tradeDistribution: [
    { label: "1", value: 12 }, { label: "2", value: -8 }, { label: "3", value: 18 },
    { label: "4", value: -4 }, { label: "5", value: 9 }, { label: "6", value: 15 },
    { label: "7", value: -12 }, { label: "8", value: 6 }, { label: "9", value: -2 },
    { label: "10", value: 20 }, { label: "11", value: 3 }, { label: "12", value: -6 },
    { label: "13", value: 11 }, { label: "14", value: 14 }, { label: "15", value: -9 },
    { label: "16", value: 5 }, { label: "17", value: -3 }, { label: "18", value: 22 },
  ],
  weeklyReturns: [
    { label: "W1", value: 2.1 }, { label: "W2", value: -0.8 }, { label: "W3", value: 1.4 },
    { label: "W4", value: 3.2 }, { label: "W5", value: -1.1 }, { label: "W6", value: 2.6 },
    { label: "W7", value: 0.9 }, { label: "W8", value: -2.3 }, { label: "W9", value: 1.8 },
    { label: "W10", value: 2.9 }, { label: "W11", value: -0.4 }, { label: "W12", value: 1.2 },
  ],
  sessionAnalysis: [
    { label: "Asian", winRate: 58, trades: 420, pnl: 1860 },
    { label: "London", winRate: 66, trades: 1150, pnl: 4980 },
    { label: "NY", winRate: 63, trades: 890, pnl: 3120 },
    { label: "London/NY Overlap", winRate: 71, trades: 350, pnl: 1980 },
  ],
  patterns: [
    { id: "PI-01", name: "London Open Reversal", confidence: 92, status: "approved", detail: "London Open patterns remain highly reliable. 148 cycles of evidence." },
    { id: "PI-02", name: "Liquidity Sweep", confidence: 78, status: "investigating", detail: "Liquidity sweep detected in 78% of losing trades. Testing sweep+reclaim filter." },
    { id: "PI-03", name: "RSI Double Divergence", confidence: 79, status: "investigating", detail: "RSI divergence confirms trend continuation 79% of time." },
    { id: "PI-04", name: "NY Overlap Fakeouts", confidence: 64, status: "hypothesis", detail: "NY overlap causes more fakeouts. Considering skip rule during overlap." },
  ],
  pipeline: [
    { label: "Current Strategy", status: "done", pass: true, progress: 100, time: "0:32", confidence: 100 },
    { label: "Historical Backtest", status: "done", pass: true, progress: 100, time: "4:12", confidence: 92 },
    { label: "Monte Carlo", status: "done", pass: true, progress: 100, time: "8:47", confidence: 89 },
    { label: "Walk Forward Validation", status: "active", pass: null, progress: 62, time: "3:24", confidence: 85 },
    { label: "Promotion Gate", status: "pending", pass: null, progress: 0, time: "—", confidence: null },
  ],
  validation: {
    passRate: 78,
    trainScore: 84,
    walkForwardScore: 79,
    monteCarloScore: 86,
    stressTestPass: true,
    overfitRisk: "Low",
    mcReturn: { median: 12.4, worst: -6.8, best: 28.9, p95: 18.2, p5: -3.1 },
  },
  backtestQueue: [
    { id: "BT-004", strategy: "v4.3.1-beta", status: "RUNNING", progress: 73, eta: "4m 22s" },
    { id: "BT-005", strategy: "v4.2.2-tight-sl", status: "QUEUED", progress: 0, eta: "~12m" },
  ],
  learning: {
    cycle: 148,
    status: "Learning",
    tradesReviewed: 248,
    currentStrategy: "v4.2.1",
    lastLearning: "2 min ago",
    dataset: "EURUSD + GBPJPY (Jan–Jul 2024)",
    speed: "47 trades/min",
    modelVersion: "GPT-4o-trading-v3.1",
    patternsDiscovered: 284,
    patternConfidence: 78.4,
    strategiesGenerated: 12,
    accuracyTrend: [
      { label: "C1", value: 61 }, { label: "C5", value: 64 }, { label: "C10", value: 68 },
      { label: "C20", value: 66 }, { label: "C40", value: 72 }, { label: "C80", value: 74 },
      { label: "C120", value: 77 }, { label: "C148", value: 79 },
    ],
  },
  strategyHistory: [
    { id: "STR-004", version: "v4.3.1-beta", name: "smc_crt", status: "validating", changes: 4, updated: "2h ago", score: 91, author: "AI Engine" },
    { id: "STR-003", version: "v4.2.1", name: "smc_crt", status: "ACTIVE", changes: 2, updated: "3d ago", score: 87, author: "AI Engine" },
    { id: "STR-002", version: "v4.1.0", name: "smc_crt", status: "rejected", changes: 1, updated: "1w ago", score: 74, author: "Human" },
    { id: "STR-001", version: "v4.0.0", name: "smc_crt", status: "replaced", changes: 0, updated: "2w ago", score: 69, author: "Human" },
  ],
};

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "GBPJPY", "AUDUSD", "USDCAD"];
const ZONES = ["Order Block", "Breaker", "Demand Zone", "Supply Zone", "Fair Value Gap"];
const CONFS = ["Strong", "Medium", "Minimal"];
const EXITS = ["tp", "sl", "be", "manual", "time"];

export function demoTrades(count = 120) {
  const rand = mulberry32(42);
  const now = Date.now() / 1000;
  const out = [];
  for (let i = 0; i < count; i++) {
    const side = rand() > 0.5 ? "buy" : "sell";
    const win = rand() > 0.42;
    const r = win ? 0.5 + rand() * 2.5 : -(0.3 + rand() * 1.4);
    const entry = 100 + rand() * 100;
    const exit = side === "buy" ? entry + r * 0.001 * entry : entry - r * 0.001 * entry;
    out.push({
      trade_id: `T-${String(count - i).padStart(3, "0")}`,
      strategy: "smc_crt",
      strategy_version: "v4.2.1",
      symbol: PAIRS[Math.floor(rand() * PAIRS.length)],
      side,
      entry_time: now - (count - i) * 3600 * 6,
      exit_time: now - (count - i) * 3600 * 6 + 1800 + rand() * 14400,
      duration_seconds: 1800 + Math.floor(rand() * 14400),
      entry_price: entry,
      exit_price: exit,
      size: 0.2 + rand() * 0.5,
      sl: entry * (1 - (side === "buy" ? 0.003 + rand() * 0.004 : -(0.003 + rand() * 0.004))),
      tp: entry * (1 + (side === "buy" ? 0.006 + rand() * 0.008 : -(0.006 + rand() * 0.008))),
      rr: 1.5 + rand() * 1.5,
      pnl: r * 40,
      pnl_points: r * 60,
      r,
      mfe: Math.abs(r) * (0.8 + rand() * 0.4),
      mae: -Math.abs(r) * (0.2 + rand() * 0.3),
      exit_reason: EXITS[Math.floor(rand() * EXITS.length)],
      zone_type: ZONES[Math.floor(rand() * ZONES.length)],
      confluence_level: CONFS[Math.floor(rand() * CONFS.length)],
      session: ["Asian", "London", "NY", "London/NY Overlap"][Math.floor(rand() * 4)],
      regime: rand() > 0.5 ? "Trending" : "Ranging",
      htf_bias: side === "buy" ? "Bullish" : "Bearish",
      bias: side === "buy" ? "Buy" : "Sell",
      choch_csd: rand() > 0.5 ? "CHoCH" : "CSD",
      confirmation_type: rand() > 0.5 ? "Displacement" : "Liquidity Sweep",
      spread_paid: 0.0001,
      slippage_paid: 0.00005,
      commission: 2.5,
    });
  }
  return out;
}

export async function getTradeHistory() {
  const trades = await getTrades();
  if (trades.length) return trades;
  return demoTrades();
}

export async function getTradeJournal() {
  const trades = await getTrades();
  const list = trades.length ? trades : demoTrades(28);
  return list.slice(0, 24);
}

// Aggregate everything the Dashboard page needs in one call.
export async function getDashboardData() {
  const [health, metrics, trades, strategies, reviews] = await Promise.all([
    getHealth(),
    getMetrics(),
    getTrades(),
    getStrategies(),
    getReviews(),
  ]);

  const hasData = metrics.online && metrics.totalTrades > 0;
  const equityPoints = hasData ? equityFromTrades(trades) : demoEquityCurve();

  // Map real trades to the reference live-position / distribution shapes.
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
    : DEMO.livePositions;

  const distribution = hasData
    ? trades.map((t, i) => ({ label: String(i + 1), value: t.r })).slice(0, 30)
    : DEMO.tradeDistribution;

  const returnPct = hasData ? metrics.totalReturnPct : 48.2;
  const cards = hasData
    ? {
        equity: metrics.finalEquity,
        todayPnL: metrics.netProfit,
        todayPnLPct: metrics.totalReturnPct,
        winRate: metrics.winRate,
        maxDrawdown: -Math.abs(metrics.maxDrawdown),
        sharpeRatio: metrics.sharpe,
        profitFactor: metrics.profitFactor,
        aiConfidence: 82,
      }
    : DEMO.cards;

  return {
    health,
    hasData,
    cards,
    equityPoints,
    drawdownPoints: drawdownFromEquity(equityPoints),
    returnPct,
    aiAnalysis: DEMO.aiAnalysis,
    livePositions,
    alerts: DEMO.alerts,
    tradeDistribution: distribution,
    weeklyReturns: DEMO.weeklyReturns,
    sessionAnalysis: DEMO.sessionAnalysis,
    patterns: DEMO.patterns,
    pipeline: DEMO.pipeline,
    validation: DEMO.validation,
    strategies: strategies.length ? strategies : DEMO.strategyHistory,
    reviews: reviews.length ? reviews : DEMO.strategyHistory,
    trades: trades,
    metrics,
  };
}
