"""Stooq-Provider - kostenlose Tagesdaten ohne jede Registrierung.

Stooq stellt CSV-Dateien unter ``stooq.com/q/d/l/`` bereit. Die Futures
heissen dort ``es.f`` (S&P 500) und ``nq.f`` (Nasdaq 100). Nur Tages-,
Wochen- und Monatsdaten, dafuer ohne Konto und ohne Rate-Limit-Cookies.
"""

from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import requests

from .base import DataError, DataProvider, ProviderInfo, normalize_frame, slice_range

SYMBOL_MAP = {
    "ES=F": "es.f",
    "NQ=F": "nq.f",
    "YM=F": "ym.f",
    "RTY=F": "er2.f",
    "GC=F": "gc.f",
    "CL=F": "cl.f",
    "SPY": "spy.us",
    "QQQ": "qqq.us",
    "IWM": "iwm.us",
}

INTERVAL_MAP = {"1d": "d", "1wk": "w", "1mo": "m"}


class StooqProvider(DataProvider):
    key = "stooq"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval not in INTERVAL_MAP:
            raise DataError(f"Stooq kennt nur {sorted(INTERVAL_MAP)}, nicht {interval!r}")

        ticker = SYMBOL_MAP.get(symbol.upper(), symbol.lower())
        url = "https://stooq.com/q/d/l/"
        params = {"s": ticker, "i": INTERVAL_MAP[interval]}
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        except requests.RequestException as exc:
            raise DataError(f"Stooq nicht erreichbar: {exc}") from exc

        if resp.status_code != 200 or resp.text.strip().startswith("No data"):
            raise DataError(f"Stooq lieferte keine Daten fuer {ticker} (HTTP {resp.status_code})")

        frame = pd.read_csv(io.StringIO(resp.text))
        return slice_range(normalize_frame(frame), start, end)

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            key="stooq",
            name="Stooq",
            needs_key=False,
            key_env=None,
            asset_classes="Futures (es.f, nq.f), Aktien, Indizes",
            note="Kein Konto noetig, aber nur Tages-/Wochen-/Monatsdaten.",
            signup_url="https://stooq.com",
        )
