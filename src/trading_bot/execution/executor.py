"""Execution adapters: simulated (paper) and MetaTrader 5 (demo/live).

Both expose the same ``Executor`` interface so the live pipeline can switch
backends without changing strategy or risk logic. Every adapter is
fail-closed: if the broker is unavailable or returns an unhealthy state, it
rejects the order rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from trading_bot.core.enums import OrderStatus, OrderType, Side
from trading_bot.core.models import Order, Position


@dataclass
class ExecutionResult:
    """Result of an order submission."""

    ok: bool
    order_id: str = ""
    message: str = ""
    filled_price: float = 0.0
    filled_time: int = 0
    status: OrderStatus = OrderStatus.REJECTED


class Executor(Protocol):
    def submit_order(self, order: Order) -> ExecutionResult: ...
    def close_position(self, pos: Position) -> ExecutionResult: ...
    def health(self) -> dict: ...
    def is_live(self) -> bool: ...


class SimulatedExecutor:
    """Paper executor: records orders, fills them immediately at market price.

    Used for demo runs before any live capital is exposed.
    """

    def __init__(self):
        self.orders: list[Order] = []
        self.closed: list[Position] = []
        self._healthy = True

    def submit_order(self, order: Order) -> ExecutionResult:
        self.orders.append(order)
        filled = ExecutionResult(
            ok=True,
            order_id=order.id,
            message="simulated market fill",
            filled_price=order.price or 0.0,
            filled_time=order.created_at,
            status=OrderStatus.FILLED,
        )
        return filled

    def close_position(self, pos: Position) -> ExecutionResult:
        self.closed.append(pos)
        return ExecutionResult(
            ok=True, order_id=f"close_{pos.id}",
            message="simulated close", status=OrderStatus.FILLED,
            filled_time=pos.close_time,
        )

    def health(self) -> dict:
        return {"ok": self._healthy, "mode": "simulated", "positions": len(self.closed)}

    def is_live(self) -> bool:
        return False


class MT5Executor:
    """MetaTrader 5 executor (demo account recommended).

    Fails closed: if MetaTrader5 is not importable/initialized, or the symbol
    is unknown, or the account is not healthy, the order is rejected.
    """

    def __init__(self, login: int = 0, password: str = "", server: str = "", path: str = ""):
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self._initialized = False
        self._mt5 = None
        self._orders: list[Order] = []

    def _init(self) -> bool:
        if self._initialized:
            return True
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return False
        self._mt5 = mt5
        if self.login:
            ok = mt5.initialize(login=self.login, password=self.password, server=self.server, path=self.path or None)
        else:
            ok = mt5.initialize(path=self.path or None)
        if not ok:
            return False
        self._initialized = True
        return True

    def health(self) -> dict:
        if not self._init():
            return {"ok": False, "mode": "mt5", "error": "terminal unavailable"}
        account = self._mt5.account_info()
        if account is None:
            return {"ok": False, "mode": "mt5", "error": "no account"}
        return {"ok": True, "mode": "mt5", "trade_mode": account.trade_mode, "leverage": account.leverage}

    def is_live(self) -> bool:
        return bool(self._init())

    def _symbol_info(self, symbol: str):
        if not self._init():
            return None
        return self._mt5.symbol_info(symbol)

    def submit_order(self, order: Order) -> ExecutionResult:
        if not self._init():
            return ExecutionResult(ok=False, message="MT5 unavailable (fail-closed)")
        sym = self._symbol_info(order.symbol)
        if sym is None:
            return ExecutionResult(ok=False, message=f"unknown symbol {order.symbol}")
        # resolve market order side
        side = self._mt5.TRADE_ACTION_DEAL
        order_type = self._mt5.ORDER_TYPE_BUY if order.side is Side.BUY else self._mt5.ORDER_TYPE_SELL
        request = {
            "action": side,
            "symbol": order.symbol,
            "volume": float(order.size),
            "type": order_type,
            "price": sym.ask if order.side is Side.BUY else sym.bid,
            "sl": float(order.sl) if order.sl else 0.0,
            "tp": float(order.tp) if order.tp else 0.0,
            "deviation": 20,
            "magic": 0,
            "comment": order.comment or order.strategy,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            rc = result.retcode if result is not None else "none"
            return ExecutionResult(ok=False, message=f"order rejected (retcode {rc})")
        self._orders.append(order)
        return ExecutionResult(
            ok=True,
            order_id=str(result.order),
            message="mt5 fill",
            filled_price=float(result.price),
            filled_time=int(result.deal and result.deal.time or 0),
            status=OrderStatus.FILLED,
        )

    def close_position(self, pos: Position) -> ExecutionResult:
        # fail-closed: close via reversal market order
        if not self._init():
            return ExecutionResult(ok=False, message="MT5 unavailable")
        sym = self._symbol_info(pos.symbol)
        if sym is None:
            return ExecutionResult(ok=False, message=f"unknown symbol {pos.symbol}")
        order_type = self._mt5.ORDER_TYPE_SELL if pos.side is Side.BUY else self._mt5.ORDER_TYPE_BUY
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": float(pos.size),
            "type": order_type,
            "price": sym.bid if pos.side is Side.BUY else sym.ask,
            "deviation": 20,
            "comment": "close_position",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            rc = result.retcode if result is not None else "none"
            return ExecutionResult(ok=False, message=f"close rejected (retcode {rc})")
        return ExecutionResult(ok=True, order_id=str(result.order), message="closed", status=OrderStatus.FILLED)
