"""Backtest runner: wires data provider -> replay engine -> strategy -> risk.

Produces a full backtest result including trades, equity curve and metrics.
Fully offline (never touches MT5 or the broker).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.backtest.metrics import compute_metrics
from trading_bot.core.enums import Timeframe
from trading_bot.core.models import TradeRecord
from trading_bot.data.base import DataProvider, MarketDataQuery
from trading_bot.replay.engine import ExecutionConfig, ReplayConfig, ReplayEngine
from trading_bot.risk.manager import RiskConfig, RiskManager


@dataclass
class BacktestResult:
    """Aggregated result of a backtest run."""

    symbol: str = ""
    timeframe: str = ""
    start: int = 0
    end: int = 0
    n_bars: int = 0
    n_trades: int = 0
    trades: list[TradeRecord] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    equity_curve: list[dict] = field(default_factory=list)  # [{time, equity}]
    final_equity: float = 0.0
    strategy_version: str = ""
    params: dict = field(default_factory=dict)
    journal_records: list[TradeRecord] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start": self.start,
            "end": self.end,
            "n_bars": self.n_bars,
            "n_trades": self.n_trades,
            "trades": [t.to_dict() for t in self.trades],
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "final_equity": self.final_equity,
            "strategy_version": self.strategy_version,
            "params": self.params,
            "meta": self.meta,
        }


@dataclass
class BacktestConfig:
    symbol: str = "EURUSD"
    timeframe: Timeframe = Timeframe.M5
    start: int = 0
    end: int = 0
    initial_cash: float = 10_000.0
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    params: dict = field(default_factory=dict)
    seed: Optional[int] = None


class BacktestRunner:
    """Runs a strategy over historical data with a shared risk manager."""

    def __init__(self, provider: DataProvider, journal=None):
        self.provider = provider
        self.journal = journal

    def run(self, strategy, config: BacktestConfig) -> BacktestResult:
        query = MarketDataQuery(
            symbol=config.symbol,
            timeframe=config.timeframe,
            start=config.start,
            end=config.end,
        )
        candles = self.provider.load_candles(query)
        if not candles:
            return BacktestResult(
                symbol=config.symbol,
                timeframe=config.timeframe.value,
                start=config.start,
                end=config.end,
                n_bars=0,
                metrics={"error": "no_data"},
            )

        sym = self.provider.symbol_info(config.symbol)
        risk = RiskManager(config.risk, symbol_info=sym)
        replay_cfg = ReplayConfig(
            initial_cash=config.initial_cash,
            symbol_info=sym,
            execution=config.execution,
            seed=config.seed,
        )
        engine = ReplayEngine(
            candles,
            replay_cfg,
            risk_manager=risk,
            journal=self.journal,
        )
        result = engine.run(strategy)

        # Build TradeRecords from outcomes via journal
        trades = self._build_trade_records(strategy, result)

        equity_curve = [{"time": e.time, "equity": e.equity} for e in result.equity_curve]
        metrics = compute_metrics(equity_curve, trades)

        return BacktestResult(
            symbol=config.symbol,
            timeframe=config.timeframe.value,
            start=candles[0].time,
            end=candles[-1].time,
            n_bars=len(candles),
            n_trades=len(trades),
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
            final_equity=result.final_equity,
            strategy_version=strategy.version,
            params=strategy.get_params(),
            meta={
                "initial_cash": config.initial_cash,
                "execution": {
                    "slippage_points": config.execution.slippage_points,
                    "commission_per_lot": config.execution.commission_per_lot,
                },
                "seed": config.seed,
            },
        )

    def _build_trade_records(self, strategy, replay_result) -> list[TradeRecord]:
        """Convert replay TradeOutcomes into journal TradeRecords."""
        records: list[TradeRecord] = []
        for outcome in replay_result.trades:
            pos = outcome.position
            rec = TradeRecord(
                trade_id=pos.id,
                strategy=pos.strategy or strategy.name,
                strategy_version=pos.strategy_version or strategy.version,
                symbol=pos.symbol,
                side=pos.side,
                entry_time=pos.open_time,
                exit_time=outcome.exit_time,
                duration_seconds=outcome.exit_time - pos.open_time,
                entry_price=pos.open_price,
                exit_price=outcome.exit_price,
                size=pos.size,
                sl=pos.sl,
                tp=pos.tp,
                rr=abs(pos.tp - pos.open_price) / abs(pos.sl - pos.open_price) if pos.sl != pos.open_price else 0.0,
                pnl=outcome.pnl,
                pnl_points=outcome.pnl_points,
                r=outcome.r,
                mfe=outcome.mfe_r,
                mae=outcome.mae_r,
                exit_reason=outcome.exit_reason,
                spread_paid=0.0,
                slippage_paid=outcome.slippage_paid,
                commission=outcome.commission_paid,
            )
            records.append(rec)
        return records
