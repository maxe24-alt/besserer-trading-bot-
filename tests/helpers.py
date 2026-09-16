"""Hilfsmittel fuer die Tests: kuenstliche Kursreihen ohne Netzzugriff."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_bars(closes: list[float], start: str = "2020-01-01", freq: str = "D") -> pd.DataFrame:
    """Baut OHLCV-Bars aus einer Liste von Schlusskursen.

    Open ist der vorherige Schluss (beim ersten Bar der Schluss selbst),
    High und Low umschliessen beide - so bleiben die Bars plausibel.
    """
    index = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    close = np.asarray(closes, dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=index,
    )


def trending_bars(periods: int = 400, slope: float = 0.5, start_price: float = 100.0) -> pd.DataFrame:
    """Gleichmaessig steigende Kurse - jede Trendfolge muss hier verdienen."""
    return make_bars([start_price + slope * i for i in range(periods)])


def wave_bars(periods: int = 400, amplitude: float = 10.0, base: float = 100.0) -> pd.DataFrame:
    """Saubere Sinuswelle - der Fall fuer Mean Reversion."""
    return make_bars([base + amplitude * np.sin(i / 8.0) for i in range(periods)])


def noisy_bars(
    periods: int = 500,
    seed: int = 7,
    start_price: float = 100.0,
    drift: float = 0.05,
    noise: float = 1.0,
) -> pd.DataFrame:
    """Random Walk mit festem Seed - reproduzierbar und trotzdem realistisch."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, noise, periods)
    return make_bars(list(start_price + np.cumsum(steps)))


def mean_reverting_bars(
    periods: int = 800,
    seed: int = 3,
    base: float = 100.0,
    pull: float = 0.12,
    noise: float = 1.4,
) -> pd.DataFrame:
    """Ornstein-Uhlenbeck-Prozess: Kurse, die zum Mittelwert zurueckkehren.

    Der ehrliche Testfall fuer Mean Reversion. Eine glatte Sinuswelle taugt
    dafuer nicht: ist ihre Periode laenger als das Indikatorfenster, laufen
    die Baender dem Kurs hinterher und die Strategie kauft systematisch in
    den Abwaertsschwung hinein.
    """
    rng = np.random.default_rng(seed)
    value = 0.0
    closes = []
    for _ in range(periods):
        value += -pull * value + rng.normal(0.0, noise)
        closes.append(base + value)
    return make_bars(closes)
