"""Fallback market-data provider.

Provides historical candles using a prioritized provider chain.

Current priority:

    1. MT5
    2. JSONL

The provider chooses the first source that can supply the requested
time range. Candle ranges are treated according to their timeframe
boundaries, so a request does not fail merely because its Unix timestamp
falls inside the first/last candle.

It also exposes metadata describing which provider was actually used,
so the API/dashboard can show the active data source.

This provider is read-only and never places orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo


@dataclass(frozen=True)
class ProviderAttempt:
    """Record of one provider attempt."""

    provider: str
    ok: bool
    n_bars: int = 0
    reason: str = ""


class FallbackDataProvider(DataProvider):
    """Try multiple data providers in priority order.

    The first provider with sufficient timeframe coverage wins.

    Example:

        FallbackDataProvider(
            providers=[
                mt5_provider,
                jsonl_provider,
            ]
        )

    By default, the provider allows normal candle-boundary differences.
    For example, an M5 request starting at 12:03 can legitimately use
    the 12:00 candle as its first available candle.
    """

    name = "fallback"

    def __init__(
        self,
        providers: Sequence[DataProvider],
        strict_range: bool = True,
        edge_tolerance_seconds: int = 4 * 86400,
    ):
        if not providers:
            raise ValueError(
                "FallbackDataProvider requires at least one provider"
            )

        self.providers = list(providers)
        self.strict_range = strict_range
        # Markets close on weekends/holidays: the first/last candle of a
        # range may legitimately sit days away from a calendar boundary.
        self.edge_tolerance_seconds = edge_tolerance_seconds

        self._last_provider: Optional[str] = None
        self._last_attempts: list[ProviderAttempt] = []
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        """Load candles using the first provider with sufficient coverage."""

        self._last_provider = None
        self._last_attempts = []
        self._last_error = ""

        for provider in self.providers:
            provider_name = self._provider_name(provider)

            try:
                candles = list(provider.load_candles(query))
            except Exception as exc:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        n_bars=0,
                        reason=f"provider error: {exc}",
                    )
                )
                continue

            if not candles:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        n_bars=0,
                        reason="no data returned",
                    )
                )
                continue

            candles.sort(key=lambda candle: candle.time)

            coverage_ok, reason = self._has_required_coverage(
                candles,
                query,
            )

            if not coverage_ok:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        n_bars=len(candles),
                        reason=reason,
                    )
                )
                continue

            self._last_provider = provider_name

            self._last_attempts.append(
                ProviderAttempt(
                    provider=provider_name,
                    ok=True,
                    n_bars=len(candles),
                    reason="complete requested range",
                )
            )

            return candles

        self._last_error = self._build_failure_message(query)

        raise RuntimeError(self._last_error)

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def _has_required_coverage(
        self,
        candles: Sequence[Candle],
        query: MarketDataQuery,
    ) -> tuple[bool, str]:
        """Check whether candles cover the requested timeframe.

        A request timestamp does not necessarily sit on a candle boundary.

        Example for M5:

            requested_start = 12:03
            first candle    = 12:00

        That is valid coverage.

        Likewise:

            requested_end = 14:03
            last candle   = 14:00

        is valid because the 14:00 candle covers 14:00 -> 14:05.

        We therefore compare against the candle's timeframe boundaries
        rather than requiring exact timestamp equality.
        """

        if not candles:
            return False, "no candles"

        if not self.strict_range:
            return True, "range checking disabled"

        first = candles[0].time
        last = candles[-1].time

        requested_start = query.start
        requested_end = query.end

        tf_seconds = query.timeframe.minutes * 60

        # --------------------------------------------------------------
        # Start coverage
        # --------------------------------------------------------------
        #
        # The first candle covers:
        #
        #     first -> first + timeframe
        #
        # Therefore the requested start is covered if it is inside that
        # candle or later.
        #
        # We allow the first candle to start slightly AFTER requested_start
        # only when the requested start falls within the previous candle.
        #
        # More simply: if the gap is <= one timeframe, the request is
        # considered candle-boundary compatible.
        #
        if requested_start:
            start_gap = first - requested_start

            allowed_start_gap = max(tf_seconds, self.edge_tolerance_seconds)
            if start_gap > allowed_start_gap:
                return (
                    False,
                    f"history starts too late "
                    f"(first={first}, requested_start={requested_start})",
                )

        # --------------------------------------------------------------
        # End coverage
        # --------------------------------------------------------------
        #
        # The last candle covers:
        #
        #     last -> last + timeframe
        #
        # So an end timestamp inside that candle is still covered.
        #
        if requested_end:
            end_gap = requested_end - last

            allowed_end_gap = max(tf_seconds, self.edge_tolerance_seconds)
            if end_gap > allowed_end_gap:
                return (
                    False,
                    f"history ends too early "
                    f"(last={last}, requested_end={requested_end})",
                )

        return True, "complete coverage"

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_name(provider: DataProvider) -> str:
        """Get a stable human-readable provider name."""

        name = getattr(provider, "name", None)

        if name:
            return str(name)

        return provider.__class__.__name__.replace(
            "DataProvider",
            "",
        ).lower()

    @property
    def active_provider(self) -> Optional[str]:
        """Provider used by the most recent successful request."""

        return self._last_provider

    @property
    def attempts(self) -> list[ProviderAttempt]:
        """Attempts made during the most recent request."""

        return list(self._last_attempts)

    @property
    def source(self) -> str:
        """Current active source or 'none'."""

        return self._last_provider or "none"

    @property
    def source_label(self) -> str:
        """Dashboard-friendly source label."""

        if self._last_provider:
            return self._last_provider.upper()

        return "No data source selected"

    def status(self) -> dict:
        """Return source-selection status for the dashboard."""

        return {
            "source": self.source,
            "source_label": self.source_label,
            "last_error": self._last_error,
            "attempts": [
                {
                    "provider": attempt.provider,
                    "ok": attempt.ok,
                    "n_bars": attempt.n_bars,
                    "reason": attempt.reason,
                }
                for attempt in self._last_attempts
            ],
        }

    # ------------------------------------------------------------------
    # Other DataProvider methods
    # ------------------------------------------------------------------

    def resample(self, timeframe: Timeframe) -> DataProvider:
        """Resample every member so higher-timeframe requests
        (e.g. walk-forward analysis on 15m/1h bars) work offline from a
        single-base-timeframe source such as the JSONL data folder."""
        return FallbackDataProvider(
            [p.resample(timeframe) for p in self.providers],
            strict_range=self.strict_range,
            edge_tolerance_seconds=self.edge_tolerance_seconds,
        )

    def load_ticks(self, query: MarketDataQuery):
        """Try providers in priority order for tick data."""

        self._last_provider = None
        self._last_attempts = []
        self._last_error = ""

        for provider in self.providers:
            provider_name = self._provider_name(provider)

            try:
                ticks = list(provider.load_ticks(query))
            except (
                AttributeError,
                NotImplementedError,
                RuntimeError,
            ) as exc:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        reason=f"tick data unavailable: {exc}",
                    )
                )
                continue
            except Exception as exc:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        reason=f"provider error: {exc}",
                    )
                )
                continue

            if not ticks:
                self._last_attempts.append(
                    ProviderAttempt(
                        provider=provider_name,
                        ok=False,
                        reason="no tick data returned",
                    )
                )
                continue

            self._last_provider = provider_name

            self._last_attempts.append(
                ProviderAttempt(
                    provider=provider_name,
                    ok=True,
                    n_bars=len(ticks),
                    reason="tick data returned",
                )
            )

            return ticks

        raise RuntimeError(
            f"No provider could supply tick data for "
            f"{query.symbol} {query.timeframe.value}"
        )

    def available_symbols(self) -> Sequence[str]:
        """Return the union of symbols supported by all providers."""

        symbols: set[str] = set()

        for provider in self.providers:
            try:
                symbols.update(provider.available_symbols())
            except Exception:
                continue

        return sorted(symbols)

    def symbol_info(self, symbol: str) -> SymbolInfo:
        """Return symbol information from the first provider that supports it."""

        errors = []

        for provider in self.providers:
            try:
                return provider.symbol_info(symbol)
            except Exception as exc:
                errors.append(
                    f"{self._provider_name(provider)}: {exc}"
                )

        raise KeyError(
            f"Unknown symbol {symbol}. "
            f"Provider errors: {'; '.join(errors)}"
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Return health information for every configured provider."""

        provider_health = []

        for provider in self.providers:
            name = self._provider_name(provider)

            try:
                health_fn = getattr(provider, "health", None)

                if callable(health_fn):
                    health = health_fn()
                else:
                    health = {
                        "ok": True,
                        "source": name,
                    }

            except Exception as exc:
                health = {
                    "ok": False,
                    "source": name,
                    "error": str(exc),
                }

            provider_health.append(
                {
                    "provider": name,
                    **health,
                }
            )

        return {
            "ok": any(
                item.get("ok", False)
                for item in provider_health
            ),
            "active_source": self.source,
            "providers": provider_health,
        }

    # ------------------------------------------------------------------
    # Error reporting
    # ------------------------------------------------------------------

    def _build_failure_message(
        self,
        query: MarketDataQuery,
    ) -> str:
        """Create a useful error for dashboard/API/logs."""

        details = [
            f"{attempt.provider}: {attempt.reason}"
            for attempt in self._last_attempts
        ]

        detail_text = " | ".join(details)

        return (
            f"No data provider could fully satisfy the requested range: "
            f"{query.symbol} {query.timeframe.value} "
            f"{query.start} -> {query.end}. "
            f"Attempts: {detail_text}"
        )


__all__ = [
    "FallbackDataProvider",
    "ProviderAttempt",
]