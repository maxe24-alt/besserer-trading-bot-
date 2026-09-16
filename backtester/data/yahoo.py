"""Yahoo-Finance-Provider - die Standardquelle.

Kein Konto, kein API-Key, kein Ausweis. Yahoo liefert ueber die oeffentliche
Chart-API die fortlaufenden Front-Month-Kontrakte von CME:

    ES=F   E-mini S&P 500        NQ=F   E-mini Nasdaq 100
    MES=F  Micro E-mini S&P      MNQ=F  Micro E-mini Nasdaq

Tagesdaten reichen bis 2000 zurueck, Intraday nur begrenzt (siehe
``MAX_INTRADAY_DAYS``). Die API antwortet auf nackte Requests haeufig mit
HTTP 429; deshalb waermt der Provider zuerst eine Session auf, um die
Consent-Cookies einzusammeln.
"""

from __future__ import annotations

import datetime as dt
import random
import time

import pandas as pd
import requests

from .base import DataError, DataProvider, ProviderInfo, normalize_frame, slice_range

CHART_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# Yahoo begrenzt, wie weit Intraday-Daten zurueckreichen.
MAX_INTRADAY_DAYS: dict[str, int] = {
    "1m": 7,
    "2m": 59,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "60m": 729,
    "1h": 729,
}


class YahooProvider(DataProvider):
    key = "yahoo"

    def __init__(self, timeout: int = 30, retries: int = 4) -> None:
        self.timeout = timeout
        self.retries = retries
        self._session: requests.Session | None = None

    # -- Session -----------------------------------------------------------
    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        # Aufwaermen: holt die Cookies, ohne die Yahoo mit 429 antwortet.
        for url in ("https://finance.yahoo.com/quote/ES%3DF", "https://fc.yahoo.com"):
            try:
                s.get(url, timeout=self.timeout)
            except requests.RequestException:
                continue
        self._session = s
        return s

    # -- Download ----------------------------------------------------------
    def fetch(
        self,
        symbol: str,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        interval = _yahoo_interval(interval)
        start, end = _clamp_intraday(start, end, interval)

        params = {
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "interval": interval,
            "includePrePost": "false",
            "events": "div,split",
        }

        last_error: Exception | None = None
        session = self._get_session()
        for attempt in range(self.retries):
            host = CHART_HOSTS[attempt % len(CHART_HOSTS)]
            url = f"https://{host}/v8/finance/chart/{requests.utils.quote(symbol)}"
            try:
                resp = session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    raise DataError("Yahoo drosselt die Anfrage (HTTP 429)")
                if resp.status_code != 200:
                    raise DataError(f"Yahoo antwortete mit HTTP {resp.status_code}")
                return _parse_chart(resp.json(), symbol, start, end)
            except (requests.RequestException, DataError, ValueError) as exc:
                last_error = exc
                # Cookies verfallen; beim Retry eine frische Session aufbauen.
                self._session = None
                session = self._get_session()
                if attempt < self.retries - 1:
                    time.sleep(1.5 * (2**attempt) + random.random())

        raise DataError(f"Yahoo-Download fuer {symbol} fehlgeschlagen: {last_error}")

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            key="yahoo",
            name="Yahoo Finance",
            needs_key=False,
            key_env=None,
            asset_classes="Futures (ES=F, NQ=F, MES=F, MNQ=F), Aktien, ETFs, Krypto",
            note="Kein Konto, kein Ausweis. Tagesdaten ab 2000, Intraday 1h/730d, 5m/60d, 1m/7d.",
            signup_url="https://finance.yahoo.com",
        )


def _yahoo_interval(interval: str) -> str:
    alias = {"60m": "1h", "1H": "1h", "1D": "1d", "daily": "1d", "4h": "1h"}
    iv = alias.get(interval, interval)
    allowed = {"1m", "2m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
    if iv not in allowed:
        raise DataError(f"Yahoo unterstuetzt das Intervall {interval!r} nicht. Moeglich: {sorted(allowed)}")
    return iv


def _clamp_intraday(start: dt.datetime, end: dt.datetime, interval: str) -> tuple[dt.datetime, dt.datetime]:
    """Kappt den Startzeitpunkt auf das, was Yahoo fuer das Intervall hergibt."""
    limit_days = MAX_INTRADAY_DAYS.get(interval)
    if limit_days is None:
        return start, end
    earliest = end - dt.timedelta(days=limit_days)
    return (max(start, earliest), end)


def _parse_chart(payload: dict, symbol: str, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise DataError(f"Yahoo-Fehler fuer {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise DataError(f"Yahoo lieferte keine Daten fuer {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    if not timestamps:
        raise DataError(f"Yahoo lieferte keine Bars fuer {symbol} im gewaehlten Zeitraum")

    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    frame = pd.DataFrame(
        {
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    return slice_range(normalize_frame(frame), start, end)
