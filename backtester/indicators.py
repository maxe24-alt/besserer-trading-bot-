"""Technische Indikatoren auf Basis von pandas - ohne TA-Lib.

Alle Funktionen arbeiten auf ``pd.Series``/``pd.DataFrame`` und geben Serien
mit demselben Index zurueck. Die Anlaufphase ist ``NaN``, damit im Backtest
kein Signal aus unvollstaendigen Fenstern entsteht.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --- Mittelwerte ---------------------------------------------------------
def sma(series: pd.Series, length: int) -> pd.Series:
    """Einfacher gleitender Durchschnitt."""
    return series.rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponentieller gleitender Durchschnitt."""
    out = series.ewm(span=length, adjust=False).mean()
    return out.mask(np.arange(len(series)) < length - 1)


def wma(series: pd.Series, length: int) -> pd.Series:
    """Linear gewichteter gleitender Durchschnitt."""
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(length, min_periods=length).apply(
        lambda w: float(np.dot(w, weights) / weights.sum()), raw=True
    )


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's Smoothing - Basis fuer RSI und ATR."""
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


# --- Volatilitaet --------------------------------------------------------
def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range nach Wilder."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range."""
    out = rma(true_range(df), length)
    return out.mask(np.arange(len(df)) < length)


def bollinger(series: pd.Series, length: int = 20, num_std: float = 2.0):
    """Bollinger-Baender: (unteres Band, Mittellinie, oberes Band)."""
    mid = sma(series, length)
    std = series.rolling(length, min_periods=length).std(ddof=0)
    return mid - num_std * std, mid, mid + num_std * std


# --- Oszillatoren --------------------------------------------------------
def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index (0-100) nach Wilder."""
    delta = series.diff()
    gain = rma(delta.clip(lower=0.0), length)
    loss = rma((-delta).clip(lower=0.0), length)
    rs = gain / loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.fillna(100.0).where(loss.notna() | gain.notna())
    return out.mask(np.arange(len(series)) < length)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD: (Linie, Signallinie, Histogramm)."""
    macd_line = series.ewm(span=fast, adjust=False).mean() - series.ewm(span=slow, adjust=False).mean()
    macd_line = macd_line.mask(np.arange(len(series)) < slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def stochastic(df: pd.DataFrame, k_length: int = 14, k_smooth: int = 3, d_smooth: int = 3):
    """Stochastik: (%K, %D)."""
    lowest = df["low"].rolling(k_length, min_periods=k_length).min()
    highest = df["high"].rolling(k_length, min_periods=k_length).max()
    span = (highest - lowest).replace(0.0, np.nan)
    raw_k = 100.0 * (df["close"] - lowest) / span
    percent_k = raw_k.rolling(k_smooth, min_periods=k_smooth).mean()
    percent_d = percent_k.rolling(d_smooth, min_periods=d_smooth).mean()
    return percent_k, percent_d


# --- Kanaele und Trend ---------------------------------------------------
def donchian(df: pd.DataFrame, length: int = 20):
    """Donchian-Kanal aus den letzten ``length`` Bars *vor* der aktuellen.

    Der Shift ist wichtig: sonst waere das Hoch der laufenden Bar Teil des
    Kanals und jeder Ausbruch damit per Definition unmoeglich.
    """
    upper = df["high"].rolling(length, min_periods=length).max().shift(1)
    lower = df["low"].rolling(length, min_periods=length).min().shift(1)
    return lower, (upper + lower) / 2.0, upper


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
    """Ichimoku: (Tenkan, Kijun, Senkou A, Senkou B).

    Die beiden Wolkenlinien sind bereits um ``kijun`` Bars nach vorne
    verschoben, wie es der Indikator vorsieht.
    """

    def mid(length: int) -> pd.Series:
        high = df["high"].rolling(length, min_periods=length).max()
        low = df["low"].rolling(length, min_periods=length).min()
        return (high + low) / 2.0

    tenkan_sen = mid(tenkan)
    kijun_sen = mid(kijun)
    span_a = ((tenkan_sen + kijun_sen) / 2.0).shift(kijun)
    span_b = mid(senkou_b).shift(kijun)
    return tenkan_sen, kijun_sen, span_a, span_b


def supertrend(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0):
    """Supertrend: (Linie, Richtung) mit Richtung +1 = long, -1 = short."""
    atr_values = atr(df, length)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper_basic = hl2 + multiplier * atr_values
    lower_basic = hl2 - multiplier * atr_values

    close = df["close"].to_numpy(dtype=float)
    ub = upper_basic.to_numpy(dtype=float)
    lb = lower_basic.to_numpy(dtype=float)
    n = len(df)

    final_ub = np.full(n, np.nan)
    final_lb = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    line = np.full(n, np.nan)

    started = False
    for i in range(n):
        if np.isnan(ub[i]) or np.isnan(lb[i]):
            continue
        if not started:
            final_ub[i], final_lb[i] = ub[i], lb[i]
            direction[i] = 1.0 if close[i] >= lb[i] else -1.0
            line[i] = final_lb[i] if direction[i] > 0 else final_ub[i]
            started = True
            continue

        prev = i - 1
        # Baender ziehen nur in Trendrichtung nach, nie dagegen.
        final_ub[i] = ub[i] if (ub[i] < final_ub[prev] or close[prev] > final_ub[prev]) else final_ub[prev]
        final_lb[i] = lb[i] if (lb[i] > final_lb[prev] or close[prev] < final_lb[prev]) else final_lb[prev]

        if close[i] > final_ub[prev]:
            direction[i] = 1.0
        elif close[i] < final_lb[prev]:
            direction[i] = -1.0
        else:
            direction[i] = direction[prev]

        line[i] = final_lb[i] if direction[i] > 0 else final_ub[i]

    return (
        pd.Series(line, index=df.index, name="supertrend"),
        pd.Series(direction, index=df.index, name="direction"),
    )


def rolling_vwap(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Rollierender VWAP ueber ``length`` Bars.

    Fehlt das Volumen (manche Futures-Feeds liefern es nicht), faellt die
    Funktion auf den ungewichteten Typical Price zurueck.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].fillna(0.0)
    if float(volume.sum()) <= 0:
        return typical.rolling(length, min_periods=length).mean()

    pv = (typical * volume).rolling(length, min_periods=length).sum()
    vol_sum = volume.rolling(length, min_periods=length).sum().replace(0.0, np.nan)
    return pv / vol_sum


def rolling_high(series: pd.Series, length: int) -> pd.Series:
    """Hoechstwert der letzten ``length`` Bars vor der aktuellen."""
    return series.rolling(length, min_periods=length).max().shift(1)


def rolling_low(series: pd.Series, length: int) -> pd.Series:
    """Tiefstwert der letzten ``length`` Bars vor der aktuellen."""
    return series.rolling(length, min_periods=length).min().shift(1)


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """True an der Bar, an der ``a`` ``b`` von unten schneidet."""
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """True an der Bar, an der ``a`` ``b`` von oben schneidet."""
    return (a < b) & (a.shift(1) >= b.shift(1))
