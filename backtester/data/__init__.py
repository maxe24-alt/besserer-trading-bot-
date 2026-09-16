"""Marktdaten: Provider-Registry und die zentrale ``load_bars``-Funktion."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from ..instruments import canonical_symbol
from . import cache
from .alpaca import AlpacaProvider
from .base import (
    INTERVAL_MINUTES,
    OHLCV_COLUMNS,
    DataError,
    DataProvider,
    ProviderInfo,
    normalize_frame,
    slice_range,
    to_utc,
)
from .csv_provider import CsvProvider
from .databento import DatabentoProvider
from .stooq import StooqProvider
from .yahoo import YahooProvider

PROVIDERS: dict[str, type[DataProvider]] = {
    "yahoo": YahooProvider,
    "csv": CsvProvider,
    "stooq": StooqProvider,
    "databento": DatabentoProvider,
    "alpaca": AlpacaProvider,
}

DEFAULT_PROVIDER = "yahoo"

_INSTANCES: dict[str, DataProvider] = {}


def get_provider(key: str = DEFAULT_PROVIDER) -> DataProvider:
    """Liefert eine (gecachte) Provider-Instanz."""
    key = (key or DEFAULT_PROVIDER).lower()
    if key not in PROVIDERS:
        raise DataError(f"Unbekannter Provider {key!r}. Verfuegbar: {', '.join(sorted(PROVIDERS))}")
    if key not in _INSTANCES:
        _INSTANCES[key] = PROVIDERS[key]()
    return _INSTANCES[key]


def provider_infos() -> list[ProviderInfo]:
    return [cls.info() for cls in PROVIDERS.values()]


def load_bars(
    symbol: str,
    start: dt.datetime | str,
    end: dt.datetime | str | None = None,
    interval: str = "1d",
    provider: str = DEFAULT_PROVIDER,
    use_cache: bool = True,
    max_cache_age_hours: float = 12.0,
) -> pd.DataFrame:
    """Laedt OHLCV-Bars - erst aus dem Cache, sonst vom Provider.

    Args:
        symbol: Ticker, auch als Kurzform ("ES" wird zu "ES=F").
        start: Startdatum, ``datetime`` oder ISO-String.
        end: Enddatum; ``None`` bedeutet jetzt.
        interval: "1d", "1h", "15m", "5m", "1m", ...
        provider: Schluessel aus ``PROVIDERS``.
        use_cache: Cache lesen und schreiben.
        max_cache_age_hours: Ab wann der Cache als veraltet gilt.

    Returns:
        DataFrame mit UTC-Index und den Spalten open/high/low/close/volume.
    """
    symbol = canonical_symbol(symbol)
    start_ts = to_utc(start)
    end_ts = to_utc(end) if end is not None else pd.Timestamp.now(tz="UTC")

    if start_ts >= end_ts:
        raise DataError(f"Startdatum {start_ts.date()} liegt nicht vor dem Enddatum {end_ts.date()}")

    if use_cache:
        cached = cache.read(provider, symbol, interval, start_ts, end_ts, max_cache_age_hours)
        if cached is not None:
            return slice_range(cached, start_ts, end_ts)

    df = get_provider(provider).fetch(symbol, start_ts.to_pydatetime(), end_ts.to_pydatetime(), interval)

    if use_cache:
        try:
            cache.write(provider, symbol, interval, df)
        except OSError:
            pass  # Ein nicht schreibbarer Cache darf den Backtest nicht stoppen.

    return slice_range(df, start_ts, end_ts)


def bars_per_year(df: pd.DataFrame) -> float:
    """Schaetzt die Anzahl Bars pro Jahr - Basis fuer Sharpe und CAGR."""
    if len(df) < 3:
        return 252.0
    median_gap = pd.Series(df.index).diff().median()
    if pd.isna(median_gap) or median_gap.total_seconds() <= 0:
        return 252.0

    gap_minutes = median_gap.total_seconds() / 60.0
    if gap_minutes >= 60 * 24 * 25:  # Monatsbars
        return 12.0
    if gap_minutes >= 60 * 24 * 6:  # Wochenbars
        return 52.0
    if gap_minutes >= 60 * 20:  # Tagesbars
        return 252.0
    # Intraday: Handelstage x Bars pro Tag, gemessen an den echten Daten.
    bars_per_day = df.groupby(df.index.date).size().median()
    return float(252.0 * max(bars_per_day, 1))


__all__ = [
    "PROVIDERS",
    "DEFAULT_PROVIDER",
    "INTERVAL_MINUTES",
    "OHLCV_COLUMNS",
    "DataError",
    "DataProvider",
    "ProviderInfo",
    "bars_per_year",
    "cache",
    "get_provider",
    "load_bars",
    "normalize_frame",
    "provider_infos",
    "slice_range",
    "to_utc",
]
