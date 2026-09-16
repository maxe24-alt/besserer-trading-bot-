"""Der Gauntlet: viele Strategien auf denselben Daten, gleiche Bedingungen.

Jede Strategie bekommt exakt dieselben Bars, dasselbe Startkapital und
dieselben Kosten. Nur so ist die Rangliste am Ende aussagekraeftig.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from ..data import load_bars
from ..strategies import BENCHMARK_KEY, all_keys, get as get_strategy
from .backtest import BacktestConfig, run_backtest
from .results import BacktestResult


@dataclass
class GauntletResult:
    """Alle Laeufe eines Vergleichs plus die Benchmark."""

    symbol: str
    interval: str
    start: pd.Timestamp
    end: pd.Timestamp
    initial_capital: float
    results: list[BacktestResult] = field(default_factory=list)
    benchmark: BacktestResult | None = None
    failures: dict[str, str] = field(default_factory=dict)
    bars: int = 0

    @property
    def ranked(self) -> list[BacktestResult]:
        """Ergebnisse nach Netto-P/L, bestes zuerst."""
        return sorted(self.results, key=lambda r: r.metrics.net_pnl, reverse=True)

    @property
    def winner(self) -> BacktestResult | None:
        ranked = self.ranked
        return ranked[0] if ranked else None

    @property
    def beaten_by_benchmark(self) -> int:
        """Wie viele Strategien schlechter abschneiden als Buy & Hold."""
        if self.benchmark is None:
            return 0
        bar = self.benchmark.metrics.net_pnl
        return sum(1 for r in self.results if r.metrics.net_pnl < bar)

    def leaderboard(self) -> pd.DataFrame:
        """Rangliste als DataFrame - praktisch fuer CSV-Export."""
        rows = [r.summary_row() for r in self.ranked]
        if self.benchmark is not None:
            row = self.benchmark.summary_row()
            row["strategy"] = f"{row['strategy']} (Benchmark)"
            rows.append(row)
        return pd.DataFrame(rows)

    def to_dict(self, include_series: bool = True, max_points: int = 1500) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "initial_capital": self.initial_capital,
            "bars": self.bars,
            "results": [r.to_dict(include_series, max_points) for r in self.ranked],
            "benchmark": self.benchmark.to_dict(include_series, max_points) if self.benchmark else None,
            "beaten_by_benchmark": self.beaten_by_benchmark,
            "failures": self.failures,
        }


def run_gauntlet(
    symbol: str = "ES=F",
    strategies: Iterable[str] | None = None,
    start: str | dt.datetime = "2015-01-01",
    end: str | dt.datetime | None = None,
    interval: str = "1d",
    provider: str = "yahoo",
    config: BacktestConfig | None = None,
    params: dict[str, dict[str, Any]] | None = None,
    include_benchmark: bool = True,
    use_cache: bool = True,
    df: pd.DataFrame | None = None,
) -> GauntletResult:
    """Laesst mehrere Strategien auf demselben Datensatz gegeneinander antreten.

    Args:
        symbol: Ticker, z. B. "ES=F" oder kurz "ES".
        strategies: Keys der Strategien; ``None`` nimmt alle ausser Benchmarks.
        start, end: Zeitraum.
        interval: Bar-Intervall.
        provider: Datenquelle.
        config: Kapital, Gebuehren, Positionsgroesse - fuer alle gleich.
        params: Parameter je Strategie, z. B. ``{"ema_cross": {"fast": 5}}``.
        include_benchmark: Buy & Hold als Vergleich mitlaufen lassen.
        df: Bereits geladene Bars; spart den Download.

    Returns:
        ``GauntletResult`` mit Rangliste, Benchmark und Fehlermeldungen.
    """
    cfg = config or BacktestConfig()
    keys = list(strategies) if strategies is not None else all_keys()
    param_map = params or {}

    if df is None:
        df = load_bars(symbol, start, end, interval, provider=provider, use_cache=use_cache)

    outcome = GauntletResult(
        symbol=symbol,
        interval=interval,
        start=df.index[0],
        end=df.index[-1],
        initial_capital=cfg.initial_capital,
        bars=len(df),
    )

    for key in keys:
        try:
            strategy = get_strategy(key, **param_map.get(key, {}))
            outcome.results.append(
                run_backtest(df, strategy, symbol=symbol, interval=interval, config=cfg)
            )
        except Exception as exc:  # eine kaputte Strategie darf den Lauf nicht kippen
            outcome.failures[key] = f"{type(exc).__name__}: {exc}"

    if include_benchmark and BENCHMARK_KEY not in keys:
        try:
            outcome.benchmark = run_backtest(
                df, get_strategy(BENCHMARK_KEY), symbol=symbol, interval=interval, config=cfg
            )
        except Exception as exc:
            outcome.failures[BENCHMARK_KEY] = f"{type(exc).__name__}: {exc}"

    return outcome
