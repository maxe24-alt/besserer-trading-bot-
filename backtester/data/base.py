"""Gemeinsame Basis aller Marktdaten-Provider."""

from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Unterstuetzte Intervalle -> ungefaehre Bar-Dauer in Minuten.
INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "2m": 2,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "60m": 60,
    "4h": 240,
    "1d": 60 * 24,
    "1wk": 60 * 24 * 7,
    "1mo": 60 * 24 * 30,
}


class DataError(RuntimeError):
    """Daten konnten nicht geladen werden."""


@dataclass(frozen=True)
class ProviderInfo:
    """Beschreibt einen Provider fuer CLI und Dashboard."""

    key: str
    name: str
    needs_key: bool
    key_env: str | None
    asset_classes: str
    note: str
    signup_url: str = ""


class DataProvider(abc.ABC):
    """Liefert OHLCV-Bars fuer ein Symbol.

    Rueckgabe ist immer ein ``DataFrame`` mit UTC-``DatetimeIndex`` und den
    Spalten ``open, high, low, close, volume`` - aufsteigend sortiert, ohne
    Duplikate und ohne Luecken in den Preisspalten.
    """

    key: str = "base"

    @abc.abstractmethod
    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        ...

    @classmethod
    def info(cls) -> ProviderInfo:  # pragma: no cover - von Subklassen ueberschrieben
        return ProviderInfo(
            key=cls.key,
            name=cls.__name__,
            needs_key=False,
            key_env=None,
            asset_classes="-",
            note="",
        )


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Bringt einen rohen Provider-Frame in das kanonische OHLCV-Format."""
    if df is None or len(df) == 0:
        raise DataError("Provider hat keine Bars geliefert")

    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]

    renames = {
        "date": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp",
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "vol": "volume",
        "adj close": "adj_close",
        "adjclose": "adj_close",
    }
    out = out.rename(columns={k: v for k, v in renames.items() if k in out.columns})

    if "timestamp" in out.columns:
        out = out.set_index("timestamp")

    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out.index.name = "timestamp"

    missing = [c for c in ["open", "high", "low", "close"] if c not in out.columns]
    if missing:
        raise DataError(f"Spalten fehlen im Datensatz: {', '.join(missing)}")
    if "volume" not in out.columns:
        out["volume"] = 0.0

    out = out[OHLCV_COLUMNS]
    for col in OHLCV_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out[~out.index.isna()]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0)
    out = out[~out.index.duplicated(keep="last")].sort_index()

    # Unplausible Bars aussortieren (Preise <= 0 oder High < Low).
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out = out[out["high"] >= out["low"]]

    if len(out) == 0:
        raise DataError("Nach der Bereinigung sind keine Bars uebrig")
    return out


def to_utc(value: dt.datetime | str | pd.Timestamp) -> pd.Timestamp:
    """Macht aus beliebigen Zeitangaben einen UTC-``Timestamp``."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def slice_range(df: pd.DataFrame, start: dt.datetime | None, end: dt.datetime | None) -> pd.DataFrame:
    """Schneidet den Frame auf [start, end] zu (beide Grenzen inklusive)."""
    out = df
    if start is not None:
        out = out[out.index >= to_utc(start)]
    if end is not None:
        out = out[out.index <= to_utc(end)]
    return out
