"""Execution adapters: simulated (paper) and MetaTrader 5 (demo/live).

Both expose the same ``Executor`` interface so the live pipeline can switch
backends without changing strategy or risk logic.

Safety design:
- SimulatedExecutor is always paper-only.
- MT5Executor is read-only unless ``allow_trading=True``.
- MT5Executor fails closed if MT5/account/symbol/order state is unhealthy.
- Broker-side order results are checked before reporting success.
- Position closes are only reported successful when the broker confirms them.
- Volume is normalized to the broker's min/max/step constraints.
- SL/TP are validated before an order reaches the broker.

IMPORTANT:
``allow_trading=True`` permits actual MT5 orders. Keep it False while
developing/testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_bot.core.enums import OrderStatus, OrderType, Side
from trading_bot.core.models import Order, Position


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Result of an order submission or position close."""

    ok: bool
    order_id: str = ""
    message: str = ""
    filled_price: float = 0.0
    filled_time: int = 0
    status: OrderStatus = OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# Executor interface
# ---------------------------------------------------------------------------

class Executor(Protocol):
    def submit_order(self, order: Order) -> ExecutionResult: ...

    def close_position(self, pos: Position) -> ExecutionResult: ...

    def health(self) -> dict: ...

    def is_live(self) -> bool: ...


# ---------------------------------------------------------------------------
# Simulated / paper executor
# ---------------------------------------------------------------------------

class SimulatedExecutor:
    """Paper executor.

    Orders are filled immediately without contacting a broker.

    This executor can NEVER place a real order.
    """

    def __init__(self):
        self.orders: list[Order] = []
        self.closed: list[Position] = []
        self._healthy = True

    def submit_order(self, order: Order) -> ExecutionResult:
        if not self._healthy:
            return ExecutionResult(
                ok=False,
                message="simulated executor unhealthy",
                status=OrderStatus.REJECTED,
            )

        if order.size <= 0:
            return ExecutionResult(
                ok=False,
                message="invalid order size",
                status=OrderStatus.REJECTED,
            )

        if not order.symbol:
            return ExecutionResult(
                ok=False,
                message="missing symbol",
                status=OrderStatus.REJECTED,
            )

        self.orders.append(order)

        filled_price = float(order.price)

        return ExecutionResult(
            ok=True,
            order_id=order.id,
            message="simulated market fill",
            filled_price=filled_price,
            filled_time=order.created_at,
            status=OrderStatus.FILLED,
        )

    def close_position(self, pos: Position) -> ExecutionResult:
        if not self._healthy:
            return ExecutionResult(
                ok=False,
                order_id=f"close_{pos.id}",
                message="simulated executor unhealthy",
                status=OrderStatus.REJECTED,
            )

        self.closed.append(pos)

        return ExecutionResult(
            ok=True,
            order_id=f"close_{pos.id}",
            message="simulated close",
            filled_price=0.0,
            filled_time=pos.close_time,
            status=OrderStatus.FILLED,
        )

    def health(self) -> dict:
        return {
            "ok": self._healthy,
            "mode": "simulated",
            "live": False,
            "positions_closed": len(self.closed),
            "orders": len(self.orders),
        }

    def is_live(self) -> bool:
        return False

    def shutdown(self) -> None:
        """No external connection exists, kept for interface symmetry."""
        self._healthy = False


# ---------------------------------------------------------------------------
# MetaTrader 5 executor
# ---------------------------------------------------------------------------

class MT5Executor:
    """MetaTrader 5 execution adapter.

    Default behaviour is SAFE:

        allow_trading=False

    With the default configuration this class can connect to MT5 and inspect
    the account, but it will NOT submit or close real orders.

    To permit broker execution explicitly:

        MT5Executor(allow_trading=True)

    Use this only with a demo account during development/testing.
    """

    def __init__(
        self,
        login: int = 0,
        password: str = "",
        server: str = "",
        path: str = "",
        allow_trading: bool = False,
        magic: int = 26081801,
        deviation: int = 20,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.path = path

        # Explicit safety gate.
        self.allow_trading = bool(allow_trading)

        self.magic = int(magic)
        self.deviation = int(deviation)

        self._initialized = False
        self._mt5 = None
        self._orders: list[Order] = []

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _init(self) -> bool:
        """Initialize MT5 if necessary.

        Returns False instead of throwing so callers can fail closed.
        """

        if self._initialized and self._mt5 is not None:
            return True

        try:
            import MetaTrader5 as mt5
        except ImportError:
            return False

        self._mt5 = mt5

        try:
            if self.login:
                ok = mt5.initialize(
                    login=self.login,
                    password=self.password,
                    server=self.server,
                    path=self.path or None,
                )
            else:
                ok = mt5.initialize(
                    path=self.path or None,
                )
        except Exception:
            self._initialized = False
            return False

        if not ok:
            self._initialized = False
            return False

        self._initialized = True
        return True

    def shutdown(self) -> None:
        """Disconnect from MT5."""

        if self._initialized and self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass

        self._initialized = False
        self._mt5 = None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Return broker/terminal health.

        ``ok=True`` means MT5 is connected and account information is
        available.

        It does NOT automatically mean trading is permitted by this adapter.
        """

        if not self._init():
            return {
                "ok": False,
                "mode": "mt5",
                "live": False,
                "trading_enabled": False,
                "error": "terminal unavailable",
            }

        mt = self._mt5

        try:
            terminal = mt.terminal_info()
            account = mt.account_info()
        except Exception as exc:
            return {
                "ok": False,
                "mode": "mt5",
                "live": False,
                "trading_enabled": False,
                "error": f"MT5 health check failed: {exc}",
            }

        if terminal is None:
            return {
                "ok": False,
                "mode": "mt5",
                "live": False,
                "trading_enabled": False,
                "error": "terminal_info unavailable",
            }

        if account is None:
            return {
                "ok": False,
                "mode": "mt5",
                "live": False,
                "trading_enabled": False,
                "error": "account_info unavailable",
            }

        # These are broker/terminal-level permissions.
        terminal_trade_allowed = bool(
            getattr(terminal, "trade_allowed", False)
        )

        account_trade_allowed = bool(
            getattr(account, "trade_allowed", False)
        )

        expert_allowed = bool(
            getattr(terminal, "trade_expert", False)
        )

        broker_trading_allowed = (
            terminal_trade_allowed
            and account_trade_allowed
            and expert_allowed
        )

        return {
            "ok": True,
            "mode": "mt5",
            "live": bool(self.allow_trading and broker_trading_allowed),
            "trading_enabled": bool(
                self.allow_trading and broker_trading_allowed
            ),
            "adapter_trading_enabled": self.allow_trading,
            "terminal_trade_allowed": terminal_trade_allowed,
            "account_trade_allowed": account_trade_allowed,
            "expert_allowed": expert_allowed,
            "broker_trading_allowed": broker_trading_allowed,
            "trade_mode": getattr(account, "trade_mode", None),
            "leverage": getattr(account, "leverage", None),
            "balance": getattr(account, "balance", None),
            "equity": getattr(account, "equity", None),
            "server": getattr(account, "server", ""),
            "currency": getattr(account, "currency", ""),
        }

    def is_live(self) -> bool:
        """True only when actual trading is explicitly enabled and healthy."""

        health = self.health()

        return bool(
            health.get("ok")
            and health.get("trading_enabled")
            and health.get("broker_trading_allowed")
        )

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------

    def _symbol_info(self, symbol: str):
        if not self._init():
            return None

        if not symbol:
            return None

        try:
            info = self._mt5.symbol_info(symbol)
        except Exception:
            return None

        if info is None:
            return None

        # Make sure MT5 can actually use the symbol.
        if not getattr(info, "visible", True):
            try:
                self._mt5.symbol_select(symbol, True)
                info = self._mt5.symbol_info(symbol)
            except Exception:
                return None

        return info

    def _normalize_volume(self, volume: float, symbol_info) -> float | None:
        """Normalize volume to broker min/max/step.

        Returns None if the requested size is invalid.
        """

        try:
            volume = float(volume)
        except (TypeError, ValueError):
            return None

        if volume <= 0:
            return None

        minimum = float(getattr(symbol_info, "volume_min", 0.0) or 0.0)
        maximum = float(getattr(symbol_info, "volume_max", 0.0) or 0.0)
        step = float(getattr(symbol_info, "volume_step", 0.0) or 0.0)

        if minimum <= 0 or maximum <= 0 or step <= 0:
            return None

        if volume < minimum:
            return None

        if volume > maximum:
            return None

        # Round DOWN to the nearest valid broker step.
        steps = int(volume / step)
        normalized = steps * step

        if normalized < minimum:
            return None

        if normalized > maximum:
            normalized = maximum

        # Avoid floating-point artifacts such as 0.0100000000001.
        decimals = 8
        try:
            step_string = f"{step:.8f}".rstrip("0")
            if "." in step_string:
                decimals = len(step_string.split(".")[1])
        except Exception:
            pass

        return round(normalized, decimals)

    def _validate_stops(
        self,
        side: Side,
        price: float,
        sl: float,
        tp: float,
        symbol_info,
    ) -> tuple[bool, str]:
        """Validate SL/TP direction and broker stop distance."""

        price = float(price)
        sl = float(sl or 0.0)
        tp = float(tp or 0.0)

        if price <= 0:
            return False, "invalid market price"

        # Directional validation.
        if side is Side.BUY:
            if sl and sl >= price:
                return False, "BUY stop-loss must be below entry price"

            if tp and tp <= price:
                return False, "BUY take-profit must be above entry price"

        elif side is Side.SELL:
            if sl and sl <= price:
                return False, "SELL stop-loss must be above entry price"

            if tp and tp >= price:
                return False, "SELL take-profit must be below entry price"

        else:
            return False, "unknown order side"

        # Broker minimum stop distance.
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        stops_level = int(
            getattr(symbol_info, "trade_stops_level", 0) or 0
        )

        minimum_distance = point * stops_level

        if minimum_distance > 0:
            if sl:
                if abs(price - sl) < minimum_distance:
                    return False, "stop-loss is inside broker minimum stop distance"

            if tp:
                if abs(price - tp) < minimum_distance:
                    return False, "take-profit is inside broker minimum stop distance"

        return True, ""

    # ------------------------------------------------------------------
    # Order validation
    # ------------------------------------------------------------------

    def _validate_order(self, order: Order, symbol_info) -> tuple[bool, str]:
        if not order.symbol:
            return False, "missing symbol"

        if order.side not in (Side.BUY, Side.SELL):
            return False, "invalid order side"

        if order.type not in (
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
            OrderType.STOP_LIMIT,
        ):
            return False, "unsupported order type"

        if order.size <= 0:
            return False, "order size must be greater than zero"

        if order.type is not OrderType.MARKET:
            return False, (
                "MT5Executor currently supports market execution only"
            )

        if not symbol_info:
            return False, f"unknown symbol {order.symbol}"

        if not getattr(symbol_info, "visible", True):
            return False, f"symbol {order.symbol} is not visible"

        if int(getattr(symbol_info, "trade_mode", 0)) == 0:
            return False, f"symbol {order.symbol} is not tradeable"

        return True, ""

    # ------------------------------------------------------------------
    # Submit order
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> ExecutionResult:
        """Submit a market order to MT5.

        This method will NEVER contact ``order_send`` unless:
        - MT5 is healthy
        - explicit ``allow_trading=True`` is set
        - broker/terminal trading permissions are enabled
        - symbol is valid
        - volume is valid
        - SL/TP are valid
        """

        if not self._init():
            return ExecutionResult(
                ok=False,
                message="MT5 unavailable (fail-closed)",
                status=OrderStatus.REJECTED,
            )

        # Explicit safety gate.
        if not self.allow_trading:
            return ExecutionResult(
                ok=False,
                message=(
                    "MT5 trading disabled: allow_trading=False "
                    "(safe mode)"
                ),
                status=OrderStatus.REJECTED,
            )

        health = self.health()

        if not health.get("ok"):
            return ExecutionResult(
                ok=False,
                message="MT5 health check failed",
                status=OrderStatus.REJECTED,
            )

        if not health.get("broker_trading_allowed"):
            return ExecutionResult(
                ok=False,
                message=(
                    "broker/terminal does not currently allow trading"
                ),
                status=OrderStatus.REJECTED,
            )

        symbol_info = self._symbol_info(order.symbol)

        valid, reason = self._validate_order(
            order,
            symbol_info,
        )

        if not valid:
            return ExecutionResult(
                ok=False,
                message=reason,
                status=OrderStatus.REJECTED,
            )

        volume = self._normalize_volume(
            order.size,
            symbol_info,
        )

        if volume is None:
            return ExecutionResult(
                ok=False,
                message=(
                    f"invalid volume {order.size}; "
                    f"broker range="
                    f"{symbol_info.volume_min}-"
                    f"{symbol_info.volume_max}, "
                    f"step={symbol_info.volume_step}"
                ),
                status=OrderStatus.REJECTED,
            )

        # Refresh the symbol price immediately before sending.
        tick = self._mt5.symbol_info_tick(order.symbol)

        if tick is None:
            return ExecutionResult(
                ok=False,
                message=f"no current tick for {order.symbol}",
                status=OrderStatus.REJECTED,
            )

        if order.side is Side.BUY:
            market_price = float(tick.ask)
        else:
            market_price = float(tick.bid)

        if market_price <= 0:
            return ExecutionResult(
                ok=False,
                message="invalid broker market price",
                status=OrderStatus.REJECTED,
            )

        valid, reason = self._validate_stops(
            order.side,
            market_price,
            order.sl,
            order.tp,
            symbol_info,
        )

        if not valid:
            return ExecutionResult(
                ok=False,
                message=reason,
                status=OrderStatus.REJECTED,
            )

        mt = self._mt5

        order_type = (
            mt.ORDER_TYPE_BUY
            if order.side is Side.BUY
            else mt.ORDER_TYPE_SELL
        )

        request = {
            "action": mt.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": volume,
            "type": order_type,
            "price": market_price,
            "sl": float(order.sl) if order.sl else 0.0,
            "tp": float(order.tp) if order.tp else 0.0,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": (
                order.comment
                or order.strategy
                or "AI_Self_Improving_Bot"
            ),
            "type_time": mt.ORDER_TIME_GTC,
            "type_filling": mt.ORDER_FILLING_IOC,
        }

        try:
            result = mt.order_send(request)
        except Exception as exc:
            return ExecutionResult(
                ok=False,
                message=f"MT5 order_send exception: {exc}",
                status=OrderStatus.REJECTED,
            )

        if result is None:
            return ExecutionResult(
                ok=False,
                message="MT5 order_send returned None",
                status=OrderStatus.REJECTED,
            )

        retcode = getattr(result, "retcode", None)

        if retcode != mt.TRADE_RETCODE_DONE:
            return ExecutionResult(
                ok=False,
                message=(
                    f"order rejected "
                    f"(retcode {retcode}; "
                    f"comment={getattr(result, 'comment', '')})"
                ),
                status=OrderStatus.REJECTED,
            )

        self._orders.append(order)

        filled_time = 0

        # MT5's deal field can vary between responses.
        deal = getattr(result, "deal", 0)

        if deal:
            try:
                deal_info = mt.history_deal_get(deal)
                if deal_info is not None:
                    filled_time = int(
                        getattr(deal_info, "time", 0) or 0
                    )
            except Exception:
                pass

        if not filled_time:
            filled_time = int(order.created_at)

        filled_price = float(
            getattr(result, "price", 0.0) or market_price
        )

        return ExecutionResult(
            ok=True,
            order_id=str(
                getattr(result, "order", 0)
                or getattr(result, "deal", 0)
                or order.id
            ),
            message="mt5 fill",
            filled_price=filled_price,
            filled_time=filled_time,
            status=OrderStatus.FILLED,
        )

    # ------------------------------------------------------------------
    # Close position
    # ------------------------------------------------------------------

    def close_position(self, pos: Position) -> ExecutionResult:
        """Close an existing MT5 position.

        Uses an opposite market order while explicitly referencing the
        existing broker position ticket when supported.
        """

        if not self._init():
            return ExecutionResult(
                ok=False,
                message="MT5 unavailable (fail-closed)",
                status=OrderStatus.REJECTED,
            )

        if not self.allow_trading:
            return ExecutionResult(
                ok=False,
                message=(
                    "MT5 trading disabled: allow_trading=False "
                    "(safe mode)"
                ),
                status=OrderStatus.REJECTED,
            )

        health = self.health()

        if not health.get("ok"):
            return ExecutionResult(
                ok=False,
                message="MT5 health check failed",
                status=OrderStatus.REJECTED,
            )

        if not health.get("broker_trading_allowed"):
            return ExecutionResult(
                ok=False,
                message="broker/terminal does not currently allow trading",
                status=OrderStatus.REJECTED,
            )

        if not pos.symbol:
            return ExecutionResult(
                ok=False,
                message="position has no symbol",
                status=OrderStatus.REJECTED,
            )

        if pos.size <= 0:
            return ExecutionResult(
                ok=False,
                message="position has invalid size",
                status=OrderStatus.REJECTED,
            )

        symbol_info = self._symbol_info(pos.symbol)

        if symbol_info is None:
            return ExecutionResult(
                ok=False,
                message=f"unknown symbol {pos.symbol}",
                status=OrderStatus.REJECTED,
            )

        volume = self._normalize_volume(
            pos.size,
            symbol_info,
        )

        if volume is None:
            return ExecutionResult(
                ok=False,
                message=f"invalid position volume {pos.size}",
                status=OrderStatus.REJECTED,
            )

        tick = self._mt5.symbol_info_tick(pos.symbol)

        if tick is None:
            return ExecutionResult(
                ok=False,
                message=f"no current tick for {pos.symbol}",
                status=OrderStatus.REJECTED,
            )

        mt = self._mt5

        if pos.side is Side.BUY:
            order_type = mt.ORDER_TYPE_SELL
            market_price = float(tick.bid)
        elif pos.side is Side.SELL:
            order_type = mt.ORDER_TYPE_BUY
            market_price = float(tick.ask)
        else:
            return ExecutionResult(
                ok=False,
                message="unknown position side",
                status=OrderStatus.REJECTED,
            )

        if market_price <= 0:
            return ExecutionResult(
                ok=False,
                message="invalid close market price",
                status=OrderStatus.REJECTED,
            )

        # Try to identify the actual MT5 position ticket.
        broker_position_ticket = self._find_broker_position_ticket(pos)

        request = {
            "action": mt.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": volume,
            "type": order_type,
            "price": market_price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "close_position",
            "type_time": mt.ORDER_TIME_GTC,
            "type_filling": mt.ORDER_FILLING_IOC,
        }

        # On hedging accounts this is important: it tells MT5 exactly
        # which position we intend to close.
        if broker_position_ticket is not None:
            request["position"] = broker_position_ticket

        try:
            result = mt.order_send(request)
        except Exception as exc:
            return ExecutionResult(
                ok=False,
                message=f"MT5 close order exception: {exc}",
                status=OrderStatus.REJECTED,
            )

        if result is None:
            return ExecutionResult(
                ok=False,
                message="MT5 close order returned None",
                status=OrderStatus.REJECTED,
            )

        retcode = getattr(result, "retcode", None)

        if retcode != mt.TRADE_RETCODE_DONE:
            return ExecutionResult(
                ok=False,
                order_id=f"close_{pos.id}",
                message=(
                    f"close rejected "
                    f"(retcode {retcode}; "
                    f"comment={getattr(result, 'comment', '')})"
                ),
                status=OrderStatus.REJECTED,
            )

        filled_price = float(
            getattr(result, "price", 0.0) or market_price
        )

        filled_time = 0

        deal = getattr(result, "deal", 0)

        if deal:
            try:
                deal_info = mt.history_deal_get(deal)
                if deal_info is not None:
                    filled_time = int(
                        getattr(deal_info, "time", 0) or 0
                    )
            except Exception:
                pass

        if not filled_time:
            filled_time = int(pos.close_time or 0)

        return ExecutionResult(
            ok=True,
            order_id=str(
                getattr(result, "order", 0)
                or getattr(result, "deal", 0)
                or f"close_{pos.id}"
            ),
            message="mt5 position close filled",
            filled_price=filled_price,
            filled_time=filled_time,
            status=OrderStatus.FILLED,
        )

    # ------------------------------------------------------------------
    # Broker position lookup
    # ------------------------------------------------------------------

    def _find_broker_position_ticket(self, pos: Position):
        """Try to find the broker position corresponding to our position.

        Returns None if no reliable match can be made.

        We deliberately do NOT guess based on an unrelated position.
        """

        if not self._init():
            return None

        mt = self._mt5

        try:
            positions = mt.positions_get(symbol=pos.symbol)
        except Exception:
            return None

        if positions is None:
            return None

        candidates = list(positions)

        if not candidates:
            return None

        # If our internal order_id is numeric and MT5 has a matching ticket,
        # prefer that.
        try:
            order_ticket = int(pos.order_id)
        except (TypeError, ValueError):
            order_ticket = 0

        if order_ticket:
            for broker_pos in candidates:
                ticket = int(
                    getattr(broker_pos, "ticket", 0) or 0
                )

                identifier = int(
                    getattr(broker_pos, "identifier", 0) or 0
                )

                if ticket == order_ticket or identifier == order_ticket:
                    return ticket

        # If there is exactly one broker position for the symbol, using it is
        # deterministic. Otherwise we refuse to guess.
        if len(candidates) == 1:
            return int(
                getattr(candidates[0], "ticket", 0) or 0
            ) or None

        return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def orders(self) -> list[Order]:
        """Orders accepted by the executor."""

        return list(self._orders)