"""CSV-Provider - liest Bars aus lokalen Dateien.

Damit laesst sich jeder Export (Tradovate, NinjaTrader, TradingView,
Databento, IBKR) backtesten, ohne dass ein Broker angebunden sein muss.
Erwartet wird eine Spalte mit dem Zeitstempel sowie OHLC-Spalten; die
Benennung ist flexibel (``Date``/``Datetime``/``time``, ``Open``/``o`` ...).
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd

from .base import DataError, DataProvider, ProviderInfo, normalize_frame, slice_range


class CsvProvider(DataProvider):
    key = "csv"

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory or os.environ.get("BACKTESTER_CSV_DIR", "data/csv"))

    def _locate(self, symbol: str, interval: str) -> Path:
        direct = Path(symbol)
        if direct.is_file():
            return direct

        safe = symbol.replace("=", "").replace("/", "_")
        candidates = [
            self.directory / f"{symbol}_{interval}.csv",
            self.directory / f"{safe}_{interval}.csv",
            self.directory / f"{symbol}.csv",
            self.directory / f"{safe}.csv",
        ]
        for path in candidates:
            if path.is_file():
                return path

        looked_in = self.directory.resolve()
        raise DataError(
            f"Keine CSV-Datei fuer {symbol} gefunden. Gesucht in {looked_in} "
            f"(z. B. {safe}_{interval}.csv) oder als direkter Dateipfad."
        )

    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        path = self._locate(symbol, interval)
        raw = pd.read_csv(path)
        if raw.empty:
            raise DataError(f"{path} enthaelt keine Zeilen")

        # Erste Spalte als Zeitstempel nehmen, falls keine erkannt wurde.
        lowered = {str(c).strip().lower() for c in raw.columns}
        if not lowered & {"date", "datetime", "time", "timestamp", "t"}:
            raw = raw.rename(columns={raw.columns[0]: "timestamp"})

        return slice_range(normalize_frame(raw), start, end)

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            key="csv",
            name="Lokale CSV-Dateien",
            needs_key=False,
            key_env="BACKTESTER_CSV_DIR",
            asset_classes="Alles, was exportiert werden kann",
            note="Fuer Exporte aus Tradovate, NinjaTrader, TradingView oder Databento.",
        )
