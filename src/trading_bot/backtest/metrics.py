"""Performance metrics computed from an equity curve and trade records.

All metrics are JSON-serializable plain types. ``equity_curve`` is a list of
``{"time": int, "equity": float}`` dicts (or EquityPoint objects); ``trades``
is a list of TradeRecord objects (or dicts with at least ``pnl``, ``r``,
``exit_reason``, ``duration_seconds``).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean, pstdev

from trading_bot.core.enums import ExitReason
from trading_bot.core.models import TradeRecord


def _equities(equity_curve) -> list[tuple[int, float]]:
    out = []
    for pt in equity_curve:
        if isinstance(pt, dict):
            out.append((pt["time"], pt["equity"]))
        else:
            out.append((pt.time, pt.equity))
    return out


def _as_trade(t) -> TradeRecord:
    if isinstance(t, TradeRecord):
        return t
    return TradeRecord(**t)


def compute_metrics(equity_curve, trades) -> dict:
    """Compute the full metrics dictionary for a backtest result."""
    eq = _equities(equity_curve)
    records = [_as_trade(t) for t in trades]
    initial = eq[0][1] if eq else 0.0
    final = eq[-1][1] if eq else initial
    t0 = eq[0][0] if eq else 0
    t1 = eq[-1][0] if eq else 0

    r_series = [t.r for t in records]
    pnl_series = [t.pnl for t in records]
    wins = [r for r in r_series if r > 0]
    losses = [r for r in r_series if r < 0]
    gross_profit = sum(p for p in pnl_series if p > 0)
    gross_loss = abs(sum(p for p in pnl_series if p < 0))

    dd, dd_pct, peak_equity = _max_drawdown(
    [e for _, e in eq]
    )

    m = {
        "initial_equity": initial,
        "peak_equity": peak_equity,
        "final_equity": final,
        "total_return": final - initial,
        "total_return_pct": (final / initial - 1) * 100 if initial else 0.0,
        "n_trades": len(records),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": (len(wins) / len(records) * 100) if records else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "expectancy_r": mean(r_series) if r_series else 0.0,
        "expectancy_currency": mean(pnl_series) if pnl_series else 0.0,
        "avg_win_r": mean(wins) if wins else 0.0,
        "avg_loss_r": mean(losses) if losses else 0.0,
        "avg_win_currency": mean([t.pnl for t in records if t.r > 0]) if wins else 0.0,
        "avg_loss_currency": mean([t.pnl for t in records if t.r < 0]) if losses else 0.0,
        "max_r_streak": _max_streak(r_series, "win"),
        "max_loss_streak": _max_streak(r_series, "loss"),
        "largest_win_currency": max(pnl_series, default=0.0),
        "largest_loss_currency": min(pnl_series, default=0.0),
        "max_drawdown_currency": dd,
        "max_drawdown_pct": dd_pct,
        "recovery_factor": ((final - initial) / dd) if dd > 0 else 0.0,
        "sharpe_r": _sharpe(r_series),
        "sortino_r": _sortino(r_series),
        "avg_duration_seconds": mean([t.duration_seconds for t in records]) if records else 0.0,
        "total_pnl": sum(pnl_series),
        "total_r": sum(r_series),
        "profit_trades_pct": round((len(wins) / len(records)) * 100, 2) if records else 0.0,
        "start_time": t0,
        "end_time": t1,
        "duration_days": (t1 - t0) / 86400.0 if t1 > t0 else 0.0,
        "monthly_returns_pct": _monthly_returns(eq),
        "exit_reason_counts": _exit_reason_counts(records),
    }
    return m


def _max_drawdown(
    equities: list[float],
) -> tuple[float, float, float]:
    peak = -float("inf")
    max_peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0

    for equity in equities:
        if equity > peak:
            peak = equity

        dd = peak - equity

        if dd > max_dd:
            max_dd = dd
            max_peak = peak

        if peak > 0:
            dd_pct = (peak - equity) / peak * 100

            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    return max_dd, max_dd_pct, max_peak


def _max_streak(r_series: list[float], kind: str) -> int:
    best = cur = 0
    for r in r_series:
        win = r > 0
        if (kind == "win" and win) or (kind == "loss" and not win and r < 0):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _sharpe(r_series: list[float], periods_per_year: float = 252.0) -> float:
    if len(r_series) < 2:
        return 0.0
    sd = pstdev(r_series)
    if sd == 0:
        return 0.0
    return mean(r_series) / sd * math.sqrt(periods_per_year)


def _sortino(r_series: list[float], periods_per_year: float = 252.0) -> float:
    downside = [r for r in r_series if r < 0]
    if len(downside) < 1:
        return 0.0
    dd_sd = pstdev(downside) if len(downside) > 1 else abs(downside[0])
    if dd_sd == 0:
        return 0.0
    return mean(r_series) / dd_sd * math.sqrt(periods_per_year)


def _monthly_returns(eq: list[tuple[int, float]]) -> dict[str, float]:
    if not eq:
        return {}
    months: dict[str, list[float]] = {}
    for t, e in eq:
        key = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")
        months.setdefault(key, []).append(e)
    out = {}
    keys = sorted(months)
    for i, k in enumerate(keys):
        if i == 0:
            continue
        start = months[keys[i - 1]][-1]
        end = months[k][-1]
        if start:
            out[k] = round((end / start - 1) * 100, 2)
    return out


def _exit_reason_counts(records: list[TradeRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        key = r.exit_reason.value if isinstance(r.exit_reason, ExitReason) else str(r.exit_reason)
        out[key] = out.get(key, 0) + 1
    return out
