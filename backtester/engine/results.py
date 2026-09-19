"""Datenstrukturen fuer Trades, Kennzahlen und Backtest-Ergebnisse."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


def finite_or_none(value: Any) -> Any:
    """Ersetzt ``inf`` und ``nan`` durch ``None``.

    Ein Profit-Faktor ohne einen einzigen Verlusttrade ist rechnerisch
    unendlich - als JSON ist das nicht darstellbar, und im Dashboard steht
    dafuer ein Strich.
    """
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def json_default(value: Any) -> Any:
    """Faengt Typen ab, die ``json`` nicht kennt (numpy-Zahlen, Zeitstempel).

    Ohne diesen Haken scheitert der Export an einem einzigen ``int64``.
    """
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    raise TypeError(f"{type(value).__name__} laesst sich nicht als JSON schreiben")


@dataclass
class Trade:
    """Ein abgeschlossener Trade von Einstieg bis Ausstieg."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int  # +1 long, -1 short
    units: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    bars_held: int
    return_pct: float
    mae: float = 0.0  # groesster Buchverlust waehrend des Trades
    mfe: float = 0.0  # groesster Buchgewinn waehrend des Trades
    exit_reason: str = "signal"

    def to_dict(self) -> dict[str, Any]:
        data = {key: finite_or_none(value) for key, value in asdict(self).items()}
        data["entry_time"] = self.entry_time.isoformat()
        data["exit_time"] = self.exit_time.isoformat()
        return data


@dataclass
class Metrics:
    """Alle Kennzahlen eines Laufs."""

    net_pnl: float = 0.0
    return_pct: float = 0.0
    cagr_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    longest_drawdown_days: int = 0
    trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    volatility_pct: float = 0.0
    exposure_pct: float = 0.0
    avg_bars_held: float = 0.0
    total_fees: float = 0.0
    final_equity: float = 0.0
    # Groesster Gegenwert einer einzelnen Position. Waechst die Zahl weit
    # ueber das Startkapital hinaus, stammt der Gewinn ueberwiegend aus dem
    # Zinseszins - und der laesst sich in der Praxis kaum so ausfuehren.
    max_position_value: float = 0.0

    def to_dict(self) -> dict[str, float | None]:
        return {key: finite_or_none(value) for key, value in asdict(self).items()}


@dataclass
class BacktestResult:
    """Ergebnis eines einzelnen Strategie-Laufs."""

    strategy_key: str
    strategy_label: str
    symbol: str
    interval: str
    start: pd.Timestamp
    end: pd.Timestamp
    initial_capital: float
    metrics: Metrics
    equity: pd.Series
    positions: pd.Series
    trades: list[Trade] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    category: str = ""
    error: str | None = None

    @property
    def drawdown(self) -> pd.Series:
        """Drawdown-Verlauf in Prozent (negativ oder null)."""
        peak = self.equity.cummax()
        return (self.equity / peak - 1.0) * 100.0

    def summary_row(self) -> dict[str, Any]:
        """Eine Zeile fuer die Rangliste."""
        m = self.metrics
        return {
            "key": self.strategy_key,
            "strategy": self.strategy_label,
            "category": self.category,
            "net_pnl": m.net_pnl,
            "return_pct": m.return_pct,
            "max_dd_pct": m.max_drawdown_pct,
            "trades": m.trades,
            "win_rate_pct": m.win_rate_pct,
            "profit_factor": finite_or_none(m.profit_factor),
            "sharpe": m.sharpe,
            "sortino": finite_or_none(m.sortino),
            "cagr_pct": m.cagr_pct,
            "exposure_pct": m.exposure_pct,
            "final_equity": m.final_equity,
        }

    def to_dict(self, include_series: bool = True, max_points: int = 1500) -> dict[str, Any]:
        """Serialisierung fuer Dashboard und JSON-Export."""
        payload: dict[str, Any] = {
            "key": self.strategy_key,
            "label": self.strategy_label,
            "category": self.category,
            "symbol": self.symbol,
            "interval": self.interval,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "initial_capital": self.initial_capital,
            "params": self.params,
            "metrics": self.metrics.to_dict(),
            "trades": [t.to_dict() for t in self.trades],
            "error": self.error,
        }
        if include_series:
            payload["equity"] = _downsample(self.equity, max_points)
            payload["drawdown"] = _downsample(self.drawdown, max_points)
        return payload


def _downsample(series: pd.Series, max_points: int) -> list[dict[str, Any]]:
    """Duennt eine Serie auf hoechstens ``max_points`` Punkte aus.

    Der letzte Punkt bleibt immer erhalten - sonst stimmt der Endwert im
    Chart nicht mit der Kennzahlentabelle ueberein.
    """
    if len(series) == 0:
        return []
    step = max(1, len(series) // max_points)
    sampled = series.iloc[::step]
    if sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])
    return [
        {"t": ts.isoformat(), "v": None if pd.isna(v) else round(float(v), 4)}
        for ts, v in sampled.items()
    ]
