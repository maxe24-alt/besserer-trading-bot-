"""Databento-Provider - echte CME-Daten (GLBX.MDP3).

Databento ist die sauberste kostenlose Quelle fuer ES und NQ auf Bar-Ebene:
Anmeldung mit E-Mail, kein Ausweis, 125 USD Startguthaben. Damit laesst sich
die komplette Minutenhistorie beider Kontrakte ziehen.

Symbole werden als "continuous contract" angefragt, z. B. ``ES.c.0`` fuer den
jeweils volumenstaerksten Front-Month. Der Key kommt aus ``DATABENTO_API_KEY``.
"""

from __future__ import annotations

import datetime as dt
import io
import os

import pandas as pd
import requests

from .base import DataError, DataProvider, ProviderInfo, normalize_frame, slice_range

BASE_URL = "https://hist.databento.com/v0/timeseries.get_range"

SCHEMA_BY_INTERVAL = {
    "1m": "ohlcv-1m",
    "1h": "ohlcv-1h",
    "60m": "ohlcv-1h",
    "1d": "ohlcv-1d",
}

SYMBOL_MAP = {
    "ES=F": "ES.c.0",
    "NQ=F": "NQ.c.0",
    "MES=F": "MES.c.0",
    "MNQ=F": "MNQ.c.0",
    "YM=F": "YM.c.0",
    "RTY=F": "RTY.c.0",
    "GC=F": "GC.c.0",
    "CL=F": "CL.c.0",
}

# Databento liefert Preise als Festkomma mit 9 Nachkommastellen.
PRICE_SCALE = 1e-9


class DatabentoProvider(DataProvider):
    key = "databento"

    def __init__(self, api_key: str | None = None, dataset: str = "GLBX.MDP3", timeout: int = 90) -> None:
        self.api_key = api_key or os.environ.get("DATABENTO_API_KEY", "")
        self.dataset = dataset
        self.timeout = timeout

    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if not self.api_key:
            raise DataError(
                "DATABENTO_API_KEY ist nicht gesetzt. Kostenlosen Key auf "
                "https://databento.com anlegen (E-Mail genuegt) und exportieren."
            )
        schema = SCHEMA_BY_INTERVAL.get(interval)
        if schema is None:
            raise DataError(f"Databento unterstuetzt hier {sorted(SCHEMA_BY_INTERVAL)}, nicht {interval!r}")

        params = {
            "dataset": self.dataset,
            "symbols": SYMBOL_MAP.get(symbol.upper(), symbol),
            "schema": schema,
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "stype_in": "continuous",
            "encoding": "csv",
        }
        try:
            resp = requests.get(
                BASE_URL,
                params=params,
                auth=(self.api_key, ""),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DataError(f"Databento nicht erreichbar: {exc}") from exc

        if resp.status_code == 401:
            raise DataError("Databento lehnt den API-Key ab (HTTP 401)")
        if resp.status_code != 200:
            raise DataError(f"Databento antwortete mit HTTP {resp.status_code}: {resp.text[:200]}")

        frame = pd.read_csv(io.StringIO(resp.text))
        if frame.empty:
            raise DataError(f"Databento lieferte keine Bars fuer {symbol}")

        time_col = "ts_event" if "ts_event" in frame.columns else frame.columns[0]
        out = pd.DataFrame(
            {
                "open": frame["open"].astype(float) * PRICE_SCALE,
                "high": frame["high"].astype(float) * PRICE_SCALE,
                "low": frame["low"].astype(float) * PRICE_SCALE,
                "close": frame["close"].astype(float) * PRICE_SCALE,
                "volume": frame.get("volume", 0),
            },
            index=pd.to_datetime(frame[time_col], utc=True, errors="coerce"),
        )
        return slice_range(normalize_frame(out), start, end)

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            key="databento",
            name="Databento (CME GLBX.MDP3)",
            needs_key=True,
            key_env="DATABENTO_API_KEY",
            asset_classes="Echte CME-Futures: ES, NQ, MES, MNQ, YM, RTY, GC, CL",
            note="E-Mail-Anmeldung, kein Ausweis, 125 USD Startguthaben. Beste Quelle fuer ES/NQ-Intraday.",
            signup_url="https://databento.com/signup",
        )
