"""Einfacher Parquet/CSV-Cache fuer heruntergeladene Bars.

Jeder Download landet unter ``data/cache/<provider>/<symbol>_<interval>.csv``.
Beim naechsten Lauf werden die Daten von dort gelesen, solange sie den
gewuenschten Zeitraum abdecken und nicht aelter als ``max_age_hours`` sind.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from pathlib import Path

import pandas as pd

from .base import normalize_frame, to_utc

DEFAULT_CACHE_DIR = Path(os.environ.get("BACKTESTER_CACHE_DIR", "data/cache"))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def cache_path(provider: str, symbol: str, interval: str, cache_dir: Path | None = None) -> Path:
    base = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    return base / _safe(provider) / f"{_safe(symbol)}_{_safe(interval)}.csv"


def read(
    provider: str,
    symbol: str,
    interval: str,
    start: dt.datetime,
    end: dt.datetime,
    max_age_hours: float = 12.0,
    cache_dir: Path | None = None,
) -> pd.DataFrame | None:
    """Liefert gecachte Bars oder ``None``, wenn der Cache nicht taugt."""
    path = cache_path(provider, symbol, interval, cache_dir)
    if not path.exists():
        return None
    if max_age_hours >= 0 and (time.time() - path.stat().st_mtime) > max_age_hours * 3600:
        return None
    try:
        df = pd.read_csv(path, index_col=0)
        df = normalize_frame(df)
    except Exception:
        return None

    # Der Cache muss den angefragten Zeitraum abdecken; am rechten Rand
    # lassen wir Toleranz, weil die Boerse nicht rund um die Uhr laeuft.
    want_start = to_utc(start)
    want_end = to_utc(end)
    if df.index[0] > want_start + pd.Timedelta(days=7):
        return None
    if df.index[-1] < want_end - pd.Timedelta(days=5):
        return None
    return df


def write(
    provider: str,
    symbol: str,
    interval: str,
    df: pd.DataFrame,
    cache_dir: Path | None = None,
) -> Path:
    """Schreibt Bars in den Cache und fuehrt sie mit vorhandenen zusammen."""
    path = cache_path(provider, symbol, interval, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = df
    if path.exists():
        try:
            old = normalize_frame(pd.read_csv(path, index_col=0))
            merged = pd.concat([old, df])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        except Exception:
            merged = df

    merged.to_csv(path)
    return path


def clear(cache_dir: Path | None = None) -> int:
    """Loescht alle Cache-Dateien und liefert deren Anzahl."""
    base = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    if not base.exists():
        return 0
    files = list(base.rglob("*.csv"))
    for f in files:
        f.unlink()
    return len(files)
