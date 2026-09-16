"""Alpaca-Provider - kostenloses Konto ohne Ausweis fuer Marktdaten.

Alpaca vergibt API-Keys sofort nach der E-Mail-Registrierung; fuer reine
Marktdaten und Paper-Trading ist keine Ausweispruefung noetig (die kommt erst,
wenn echtes Geld ins Spiel kommt). Futures bietet Alpaca nicht an - fuer ES
und NQ nimmt man daher die ETFs SPY und QQQ als Proxy oder greift auf
Databento zurueck.

Keys: ``APCA_API_KEY_ID`` und ``APCA_API_SECRET_KEY``.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import requests

from .base import DataError, DataProvider, ProviderInfo, normalize_frame, slice_range

BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"

TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "60m": "1Hour",
    "4h": "4Hour",
    "1d": "1Day",
    "1wk": "1Week",
}

# ES/NQ gibt es bei Alpaca nicht - diese ETFs bilden dieselben Indizes ab.
PROXY_MAP = {"ES=F": "SPY", "MES=F": "SPY", "NQ=F": "QQQ", "MNQ=F": "QQQ", "RTY=F": "IWM"}


class AlpacaProvider(DataProvider):
    key = "alpaca"

    def __init__(self, api_key: str | None = None, api_secret: str | None = None, timeout: int = 45) -> None:
        self.api_key = api_key or os.environ.get("APCA_API_KEY_ID", "")
        self.api_secret = api_secret or os.environ.get("APCA_API_SECRET_KEY", "")
        self.timeout = timeout

    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if not (self.api_key and self.api_secret):
            raise DataError(
                "APCA_API_KEY_ID / APCA_API_SECRET_KEY fehlen. Kostenloses Konto auf "
                "https://alpaca.markets anlegen (E-Mail genuegt fuer Marktdaten)."
            )
        timeframe = TIMEFRAME_MAP.get(interval)
        if timeframe is None:
            raise DataError(f"Alpaca unterstuetzt {sorted(TIMEFRAME_MAP)}, nicht {interval!r}")

        ticker = PROXY_MAP.get(symbol.upper(), symbol.upper())
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}
        params = {
            "symbols": ticker,
            "timeframe": timeframe,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 10000,
            "adjustment": "all",
            "feed": "iex",
        }

        rows: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            try:
                resp = requests.get(BASE_URL, headers=headers, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise DataError(f"Alpaca nicht erreichbar: {exc}") from exc
            if resp.status_code in (401, 403):
                raise DataError("Alpaca lehnt die Keys ab (HTTP 401/403)")
            if resp.status_code != 200:
                raise DataError(f"Alpaca antwortete mit HTTP {resp.status_code}: {resp.text[:200]}")

            payload = resp.json()
            rows.extend((payload.get("bars") or {}).get(ticker) or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        if not rows:
            raise DataError(f"Alpaca lieferte keine Bars fuer {ticker}")

        frame = pd.DataFrame(rows)
        out = pd.DataFrame(
            {
                "open": frame["o"],
                "high": frame["h"],
                "low": frame["l"],
                "close": frame["c"],
                "volume": frame.get("v", 0),
            },
            index=pd.to_datetime(frame["t"], utc=True, errors="coerce"),
        )
        return slice_range(normalize_frame(out), start, end)

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            key="alpaca",
            name="Alpaca Markets",
            needs_key=True,
            key_env="APCA_API_KEY_ID + APCA_API_SECRET_KEY",
            asset_classes="US-Aktien und ETFs (ES=F -> SPY, NQ=F -> QQQ als Proxy)",
            note="E-Mail-Registrierung, kein Ausweis fuer Marktdaten und Paper-Trading. Keine Futures.",
            signup_url="https://alpaca.markets/",
        )
