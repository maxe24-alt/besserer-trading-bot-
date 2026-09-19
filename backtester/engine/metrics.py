"""Berechnung der Kennzahlen aus Equity-Kurve und Trade-Liste."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .results import Metrics, Trade


def compute_metrics(
    equity: pd.Series,
    trades: list[Trade],
    positions: pd.Series,
    initial_capital: float,
    periods_per_year: float = 252.0,
    risk_free_rate: float = 0.0,
    total_fees: float = 0.0,
    max_position_value: float = 0.0,
) -> Metrics:
    """Fuehrt Equity-Kurve und Trades zu einem Kennzahlensatz zusammen.

    Args:
        equity: Kontostand je Bar.
        trades: Abgeschlossene Trades.
        positions: Gehaltene Position je Bar (fuer die Marktzeit).
        initial_capital: Startkapital.
        periods_per_year: Bars pro Jahr - skaliert Sharpe, Sortino und Vola.
        risk_free_rate: Risikoloser Zins p. a. als Dezimalzahl (0.04 = 4 %).
        total_fees: Summe aller Gebuehren.
    """
    metrics = Metrics(total_fees=round(total_fees, 2),
                      max_position_value=round(max_position_value, 2))
    if len(equity) == 0:
        return metrics

    final_equity = float(equity.iloc[-1])
    metrics.final_equity = round(final_equity, 2)
    metrics.net_pnl = round(final_equity - initial_capital, 2)
    metrics.return_pct = round((final_equity / initial_capital - 1.0) * 100.0, 2) if initial_capital else 0.0

    # --- Drawdown ---
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    metrics.max_drawdown_pct = round(float(drawdown.min()) * 100.0, 2)
    metrics.max_drawdown_abs = round(float((equity - peak).min()), 2)
    metrics.longest_drawdown_days = _longest_drawdown_days(equity, peak)

    # --- Zeitbasierte Groessen ---
    years = _years_covered(equity)
    if years > 0 and initial_capital > 0 and final_equity > 0:
        metrics.cagr_pct = round(((final_equity / initial_capital) ** (1.0 / years) - 1.0) * 100.0, 2)

    returns = equity.pct_change().dropna()
    returns = returns[np.isfinite(returns)]
    if len(returns) > 1:
        std = float(returns.std(ddof=1))
        mean = float(returns.mean())
        metrics.volatility_pct = round(std * np.sqrt(periods_per_year) * 100.0, 2)

        rf_per_period = risk_free_rate / periods_per_year
        excess = mean - rf_per_period
        if std > 0:
            metrics.sharpe = round(excess / std * np.sqrt(periods_per_year), 2)

        # Target Downside Deviation nach Sortino/Satchell: die Quadrate der
        # Unterschreitungen werden durch ALLE Perioden geteilt, nicht nur durch
        # die negativen - sonst faellt Sortino faelschlich unter Sharpe.
        shortfall = np.minimum(returns.to_numpy() - rf_per_period, 0.0)
        downside_std = float(np.sqrt(np.mean(np.square(shortfall))))
        if downside_std > 0:
            metrics.sortino = round(excess / downside_std * np.sqrt(periods_per_year), 2)
        elif excess > 0:
            metrics.sortino = float("inf")

    if metrics.max_drawdown_pct < 0:
        metrics.calmar = round(metrics.cagr_pct / abs(metrics.max_drawdown_pct), 2)

    # --- Marktzeit ---
    if len(positions):
        metrics.exposure_pct = round(float((positions != 0).mean()) * 100.0, 2)

    # --- Trade-Statistik ---
    metrics.trades = len(trades)
    if trades:
        pnls = np.array([t.net_pnl for t in trades], dtype=float)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]

        metrics.win_rate_pct = round(len(wins) / len(pnls) * 100.0, 2)
        metrics.expectancy = round(float(pnls.mean()), 2)
        metrics.avg_win = round(float(wins.mean()), 2) if len(wins) else 0.0
        metrics.avg_loss = round(float(losses.mean()), 2) if len(losses) else 0.0
        metrics.largest_win = round(float(pnls.max()), 2)
        metrics.largest_loss = round(float(pnls.min()), 2)
        metrics.avg_bars_held = round(float(np.mean([t.bars_held for t in trades])), 1)

        if metrics.net_pnl > 0:
            metrics.top_trade_share_pct = round(float(pnls.max()) / metrics.net_pnl * 100.0, 1)

        gross_profit = float(wins.sum())
        gross_loss = abs(float(losses.sum()))
        if gross_loss > 0:
            metrics.profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            metrics.profit_factor = float("inf")

    return metrics


def _years_covered(equity: pd.Series) -> float:
    """Laenge der Kurve in Jahren."""
    if len(equity) < 2:
        return 0.0
    span = equity.index[-1] - equity.index[0]
    return max(span.total_seconds() / (365.25 * 24 * 3600), 0.0)


def _longest_drawdown_days(equity: pd.Series, peak: pd.Series) -> int:
    """Laengste Phase unter dem alten Hoch, in Kalendertagen."""
    under_water = equity < peak
    if not bool(under_water.any()):
        return 0

    longest = pd.Timedelta(0)
    start: pd.Timestamp | None = None
    for timestamp, is_under in under_water.items():
        if is_under and start is None:
            start = timestamp
        elif not is_under and start is not None:
            longest = max(longest, timestamp - start)
            start = None
    if start is not None:
        longest = max(longest, under_water.index[-1] - start)
    return int(longest.days)
