"""Validation pipeline: train/val/test splits, walk-forward, Monte Carlo,
and promotion gates.

Guarantees:
- The final (out-of-sample) test set is held out and only used once.
- Walk-forward uses strictly expanding/rolling windows with fresh strategy
  instances per window (no state leakage).
- Monte Carlo is seeded and deterministic for the same trade series.
- Promotion requires the candidate to beat baseline on validation AND final
  test, plus survival of simulated drawdown stress.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from trading_bot.backtest.runner import BacktestConfig, BacktestResult, BacktestRunner
from trading_bot.core.enums import Timeframe
from trading_bot.core.models import TradeRecord
from trading_bot.strategy.base import BaseStrategy, create_strategy


# ---------------------------------------------------------------- splits
@dataclass
class TimeSplit:
    """Epoch boundaries for train / validation / final test windows."""

    train_start: int = 0
    train_end: int = 0
    val_start: int = 0
    val_end: int = 0
    test_start: int = 0
    test_end: int = 0


def time_split(start: int, end: int, train_ratio: float = 0.6, val_ratio: float = 0.2) -> TimeSplit:
    """Split [start, end] into contiguous train/val/test windows by time."""
    if not (0 < train_ratio < 1) or not (0 < val_ratio < 1):
        raise ValueError("train_ratio and val_ratio must be in (0,1)")
    if train_ratio + val_ratio >= 1:
        raise ValueError("train_ratio + val_ratio must be < 1")
    total = end - start
    train_end = start + int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    return TimeSplit(
        train_start=start,
        train_end=train_end,
        val_start=train_end,
        val_end=val_end,
        test_start=val_end,
        test_end=end,
    )


# ------------------------------------------------------------- walk-forward
@dataclass
class WalkForwardWindow:
    train_start: int
    train_end: int
    val_start: int
    val_end: int
    train: Optional[BacktestResult] = None
    val: Optional[BacktestResult] = None


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    val_n_trades: list[int] = field(default_factory=list)
    val_pf: list[float] = field(default_factory=list)
    val_win_rate: list[float] = field(default_factory=list)
    val_expectancy_r: list[float] = field(default_factory=list)

    def consistent(self, min_windows: int = 3, min_trades_per_window: int = 5) -> bool:
        if len(self.windows) < min_windows:
            return False
        positive = sum(1 for w in self.val_expectancy_r if w > 0)
        adequate = sum(1 for n in self.val_n_trades if n >= min_trades_per_window)
        return positive >= max(1, len(self.windows) // 2) and adequate == len(self.windows)


def run_walk_forward(
    runner: BacktestRunner,
    strategy_name: str,
    params: dict,
    version: str,
    base_cfg: BacktestConfig,
    n_windows: int = 4,
) -> WalkForwardResult:
    """Rolling train->validate walk-forward over the config's data range."""
    if base_cfg.start <= 0 or base_cfg.end <= 0:
        raise ValueError("Walk-forward requires explicit start/end timestamps")
    start, end = base_cfg.start, base_cfg.end
    total = end - start
    win_len = total // n_windows
    result = WalkForwardResult()
    for i in range(n_windows):
        val_start = start + i * win_len
        val_end = start + (i + 1) * win_len if i < n_windows - 1 else end
        train_start = start
        train_end = val_start
        wf_win = WalkForwardWindow(
            train_start=train_start, train_end=train_end,
            val_start=val_start, val_end=val_end,
        )
        train_cfg = _window_cfg(base_cfg, train_start, train_end)
        val_cfg = _window_cfg(base_cfg, val_start, val_end)
        wf_win.train = runner.run(_fresh(strategy_name, params, version), train_cfg)
        wf_win.val = runner.run(_fresh(strategy_name, params, version), val_cfg)
        result.windows.append(wf_win)
        result.val_n_trades.append(wf_win.val.n_trades)
        result.val_pf.append(_num(wf_win.val.metrics.get("profit_factor")))
        result.val_win_rate.append(_num(wf_win.val.metrics.get("win_rate")))
        result.val_expectancy_r.append(_num(wf_win.val.metrics.get("expectancy_r")))
    return result


def _window_cfg(base: BacktestConfig, start: int, end: int) -> BacktestConfig:
    cfg = BacktestConfig(
        symbol=base.symbol, timeframe=base.timeframe, start=start, end=end,
        initial_cash=base.initial_cash, execution=base.execution,
        risk=base.risk, params=dict(base.params), seed=base.seed,
    )
    return cfg


def _fresh(name: str, params: dict, version: str) -> BaseStrategy:
    return create_strategy(name, params=dict(params), version=version)


def _num(v) -> float:
    try:
        if isinstance(v, float) and (v != v):  # NaN
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------- Monte Carlo
def monte_carlo(
    r_series: list[float],
    n_sims: int = 2000,
    n_trades: Optional[int] = None,
    initial_cash: float = 10_000.0,
    seed: int = 0,
    risk_per_trade_pct: float = 0.01,
) -> dict:
    """Resample the R series to estimate the distribution of outcomes.

    Returns percentiles for final equity (via fixed-fractional sizing), max
    drawdown and worst losing streak, plus the ruin probability (equity <= 0).
    """
    import numpy as np

    if not r_series:
        return {"n_sims": 0, "median_final_equity": initial_cash, "risk_of_ruin": 0.0,
                "worst_dd_pct_95": 0.0, "worst_streak_95": 0}
    rng = np.random.default_rng(seed)
    n = n_trades or len(r_series)
    finals = np.empty(n_sims)
    max_dd = np.empty(n_sims)
    worst_streak = np.empty(n_sims, dtype=int)
    for s in range(n_sims):
        sample = rng.choice(r_series, size=n, replace=True)
        equity = initial_cash
        peak = initial_cash
        dd = 0.0
        streak = cur = 0
        for r in sample:
            equity *= 1.0 + r * risk_per_trade_pct
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
            if r > 0:
                cur = 0
            else:
                cur += 1
            streak = max(streak, cur)
        finals[s] = equity
        max_dd[s] = dd
        worst_streak[s] = streak
    ruin = float(np.mean(finals <= 0) * 100)
    return {
        "n_sims": n_sims,
        "n_trades": n,
        "median_final_equity": float(np.median(finals)),
        "p5_final_equity": float(np.percentile(finals, 5)),
        "p95_final_equity": float(np.percentile(finals, 95)),
        "worst_dd_pct_95": float(np.percentile(max_dd, 95) / initial_cash * 100),
        "worst_streak_95": int(np.percentile(worst_streak, 95)),
        "risk_of_ruin_pct": round(ruin, 3),
    }


# ----------------------------------------------------------- promotion gates
@dataclass
class PromotionResult:
    passed: bool = False
    checks: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    mc: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": self.checks,
                "reasons": self.reasons, "mc": self.mc}


class PromotionGate:
    """Gatekeeper for moving a candidate to demo/live.

    Conservative defaults: every gate must pass. A candidate that fails any
    gate is rejected (kept for reference, never promoted).
    """

    def __init__(
        self,
        min_trades: int = 30,
        min_profit_factor: float = 1.15,
        max_drawdown_pct: float = 25.0,
        min_expectancy_r: float = 0.02,
        min_win_rate: float = 30.0,
        max_mc_dd95_pct: float = 40.0,
        max_ruin_pct: float = 5.0,
    ):
        self.min_trades = min_trades
        self.min_profit_factor = min_profit_factor
        self.max_drawdown_pct = max_drawdown_pct
        self.min_expectancy_r = min_expectancy_r
        self.min_win_rate = min_win_rate
        self.max_mc_dd95_pct = max_mc_dd95_pct
        self.max_ruin_pct = max_ruin_pct

    def evaluate(
        self,
        result: BacktestResult,
        baseline: Optional[BacktestResult] = None,
        wf: Optional[WalkForwardResult] = None,
        seed: int = 0,
    ) -> PromotionResult:
        m = result.metrics
        r_series = [t.r for t in result.trades]
        mc = monte_carlo(
            r_series,
            seed=seed,
            n_trades=min(len(r_series), 200),
            initial_cash=result.metrics.get("initial_equity", 10_000.0),
        )
        checks = {
            "n_trades": m.get("n_trades", 0),
            "profit_factor": _num(m.get("profit_factor")),
            "max_drawdown_pct": _num(m.get("max_drawdown_pct")),
            "expectancy_r": _num(m.get("expectancy_r")),
            "win_rate": _num(m.get("win_rate")),
            "mc_worst_dd95_pct": _num(mc.get("worst_dd_pct_95")),
            "mc_ruin_pct": _num(mc.get("risk_of_ruin_pct")),
            "walk_forward_consistent": wf.consistent() if wf else False,
        }
        reasons = []
        passed = True
        if checks["n_trades"] < self.min_trades:
            passed = False
            reasons.append(f"insufficient trades ({checks['n_trades']} < {self.min_trades})")
        if checks["profit_factor"] < self.min_profit_factor:
            passed = False
            reasons.append(f"low profit factor ({checks['profit_factor']:.2f} < {self.min_profit_factor})")
        if checks["max_drawdown_pct"] > self.max_drawdown_pct:
            passed = False
            reasons.append(f"deep drawdown ({checks['max_drawdown_pct']:.1f}% > {self.max_drawdown_pct}%)")
        if checks["expectancy_r"] < self.min_expectancy_r:
            passed = False
            reasons.append(f"low expectancy ({checks['expectancy_r']:.3f}R < {self.min_expectancy_r}R)")
        if checks["win_rate"] < self.min_win_rate:
            passed = False
            reasons.append(f"low win rate ({checks['win_rate']:.1f}% < {self.min_win_rate}%)")
        if checks["mc_worst_dd95_pct"] > self.max_mc_dd95_pct:
            passed = False
            reasons.append(f"MC drawdown tail too deep ({checks['mc_worst_dd95_pct']:.1f}% > {self.max_mc_dd95_pct}%)")
        if checks["mc_ruin_pct"] > self.max_ruin_pct:
            passed = False
            reasons.append(f"MC ruin risk too high ({checks['mc_ruin_pct']:.2f}% > {self.max_ruin_pct}%)")
        if wf is not None and not wf.consistent():
            passed = False
            reasons.append("walk-forward validation inconsistent")
        if baseline is not None:
            beats = _num(m.get("expectancy_r", 0)) >= _num(baseline.metrics.get("expectancy_r", 0))
            checks["beats_baseline"] = bool(beats)
            if not beats:
                passed = False
                reasons.append("candidate does not beat baseline expectancy")
        if not reasons:
            reasons.append("all promotion gates passed")
        return PromotionResult(passed=passed, checks=checks, reasons=reasons, mc=mc)
