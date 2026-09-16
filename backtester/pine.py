"""Pine-Script-Export fuer TradingView.

Jede Strategie mit einer ``pine()``-Fassung laesst sich hier in ein
lauffaehiges ``strategy()``-Skript uebersetzen. Das erzeugte Skript bildet
das Ausfuehrungsmodell der Python-Engine so genau wie moeglich nach:

    Python-Engine                      Pine-Script
    -----------------------------      -----------------------------------
    Signal am Bar-Schluss,             process_orders_on_close = false
    Ausfuehrung zur naechsten Open     (Pine fuellt ebenfalls zur naechsten Open)
    sizing="equity_pct", exposure=1    default_qty_type = percent_of_equity, 100
    fee_pct = 0.1                      commission_type = percent, value = 0.1
    slippage_ticks = 1                 slippage = 1
    long_only = True                   nur strategy.entry(..., strategy.long)

Restliche Unterschiede stehen in ``KNOWN_DIFFERENCES`` und wandern als
Kommentar in den Kopf jedes erzeugten Skripts.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from .engine.backtest import BacktestConfig
from .instruments import resolve
from .strategies import Strategy, all_keys, get as get_strategy
from .strategies.base import PineSpec

PINE_VERSION = 6

# TradingView-Symbole fuer die gaengigen Kontrakte (fortlaufender Frontmonat).
TRADINGVIEW_SYMBOLS: dict[str, str] = {
    "ES=F": "CME_MINI:ES1!",
    "NQ=F": "CME_MINI:NQ1!",
    "MES=F": "CME_MINI:MES1!",
    "MNQ=F": "CME_MINI:MNQ1!",
    "YM=F": "CBOT_MINI:YM1!",
    "RTY=F": "CME_MINI:RTY1!",
    "GC=F": "COMEX:GC1!",
    "CL=F": "NYMEX:CL1!",
    "SPY": "AMEX:SPY",
    "QQQ": "NASDAQ:QQQ",
    "IWM": "AMEX:IWM",
    "BTC-USD": "BITSTAMP:BTCUSD",
    "ETH-USD": "BITSTAMP:ETHUSD",
}

KNOWN_DIFFERENCES = (
    "Kontraktstueckelung: TradingView rundet die Positionsgroesse bei Futures auf",
    "ganze Kontrakte, die Python-Engine rechnet mit Bruchteilen. Bei kleinem",
    "Startkapital weichen die Zahlen dadurch sichtbar ab.",
    "Historie: Im TradingView-Gratisplan ist die Zahl der Bars begrenzt, ein",
    "sehr langer Intraday-Test wird dort also kuerzer ausfallen.",
    "Anlaufphase: Supertrend und Ichimoku starten in Pine minimal anders,",
    "das betrifft nur die ersten Bars.",
)


def tradingview_symbol(symbol: str) -> str:
    """Uebersetzt ein internes Symbol in den TradingView-Ticker."""
    return TRADINGVIEW_SYMBOLS.get(resolve(symbol).symbol, symbol)


def _pine_timestamp(value: pd.Timestamp | dt.datetime | str) -> str:
    """Baut einen ``timestamp(...)``-Aufruf fuer Pine."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return f'timestamp("{ts.strftime("%d %b %Y %H:%M")} +0000")'


def _escape(text: str) -> str:
    """Macht Text fuer einen Pine-String sicher."""
    return text.replace("\\", "").replace('"', "'")


def _short_title(name: str, limit: int = 15) -> str:
    """Kuerzt den Namen fuer ``shorttitle``, ohne Klammern aufzubrechen.

    Ein abgeschnittenes "(" wuerde den Klammerzaehler des Skripts verbiegen,
    deshalb wird an der letzten unbedenklichen Stelle getrennt.
    """
    short = _escape(name)[:limit].rstrip()
    if short.count("(") != short.count(")"):
        short = short[: short.rindex("(")].rstrip()
    return short or "Strategie"


def _pine_number(value: float | int) -> str:
    """Zahlen so schreiben, wie Pine sie erwartet (float braucht einen Punkt)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.10g}" if float(value) != int(value) else f"{float(value):.1f}"


def to_pine(
    strategy: Strategy | str,
    symbol: str = "ES=F",
    start: pd.Timestamp | dt.datetime | str = "2015-01-01",
    end: pd.Timestamp | dt.datetime | str | None = None,
    interval: str = "1d",
    config: BacktestConfig | None = None,
    **strategy_params,
) -> str:
    """Erzeugt den vollstaendigen Pine-Quelltext einer Strategie.

    Args:
        strategy: Instanz oder Registry-Key.
        symbol: Ticker - bestimmt den TradingView-Hinweis im Kopf.
        start, end: Zeitfenster, das im Skript als Input voreingestellt wird.
        interval: Bar-Intervall, nur als Hinweis im Kommentarkopf.
        config: Kapital, Gebuehren und Slippage - dieselben wie im Backtest.
        **strategy_params: Parameter, falls ``strategy`` ein Key ist.

    Returns:
        Pine-Quelltext als String, bereit zum Einfuegen in den Pine-Editor.

    Raises:
        ValueError: Wenn die Strategie keine Pine-Fassung hat.
    """
    if isinstance(strategy, str):
        strategy = get_strategy(strategy, **strategy_params)

    spec = strategy.pine()
    if spec is None:
        raise ValueError(
            f"Die Strategie {strategy.key!r} hat keine Pine-Fassung "
            "(sie laesst sich nur in Python backtesten)."
        )

    cfg = config or BacktestConfig()
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp.now("UTC")
    tv_symbol = tradingview_symbol(symbol)

    lines: list[str] = [
        f"//@version={PINE_VERSION}",
        "// ---------------------------------------------------------------------",
        f"// {_escape(strategy.label)}",
        "// Erzeugt vom Python-Backtester - siehe README.",
        "//",
        f"// Gedacht fuer: {tv_symbol}   Zeiteinheit: {_interval_label(interval)}",
        f"// Gleiche Bedingungen wie im Python-Lauf: {_pine_number(cfg.initial_capital)} USD Start, "
        f"{_pine_number(cfg.fee_pct)} % Gebuehr je Seite, {_pine_number(cfg.slippage_ticks)} Tick Slippage.",
        "//",
        "// Bekannte Abweichungen gegenueber der Python-Engine:",
    ]
    lines += [f"//   {line}" for line in KNOWN_DIFFERENCES]
    lines += [
        "// ---------------------------------------------------------------------",
        "",
        "strategy(",
        f'     title = "{_escape(strategy.label)} [backtester]",',
        f'     shorttitle = "{_short_title(strategy.display_name)}",',
        f"     overlay = {str(spec.overlay).lower()},",
        f"     initial_capital = {int(cfg.initial_capital)},",
        "     default_qty_type = strategy.percent_of_equity,",
        f"     default_qty_value = {_pine_number(cfg.exposure * 100)},",
        "     commission_type = strategy.commission.percent,",
        f"     commission_value = {_pine_number(cfg.fee_pct)},",
        f"     slippage = {int(round(cfg.slippage_ticks))},",
        "     pyramiding = 0,",
        "     process_orders_on_close = false,",
        "     calc_on_every_tick = false,",
        "     currency = currency.USD)",
        "",
        "// --- Zeitfenster -----------------------------------------------------",
        f'startDate = input.time({_pine_timestamp(start)}, "Backtest ab", group="Zeitraum")',
        f'endDate = input.time({_pine_timestamp(end_ts)}, "Backtest bis", group="Zeitraum")',
        "inWindow = time >= startDate and time <= endDate",
        "",
    ]

    if spec.inputs:
        lines.append("// --- Parameter -------------------------------------------------------")
        settings = dict(strategy.settings)
        for template in spec.inputs:
            lines.append(template.format(**{k: _pine_number(v) for k, v in settings.items()}))
        lines.append("")

    if spec.calc:
        lines.append("// --- Indikatoren -----------------------------------------------------")
        lines.extend(spec.calc)
        lines.append("")

    lines.append("// --- Regeln ----------------------------------------------------------")
    lines.append(f"longEntry = {spec.long_entry}")
    lines.append(f"longExit = {spec.long_exit}")
    lines.append("")
    lines.append("// --- Orders ----------------------------------------------------------")
    lines.append("// Pine fuellt Orders zur Eroeffnung der naechsten Bar - genau wie die")
    lines.append("// Python-Engine. Der Ausstieg wird zuerst geprueft, damit an einer Bar")
    lines.append("// mit beiden Signalen nicht sofort neu eingestiegen wird.")
    lines.append("if inWindow")
    lines.append("    if longExit and strategy.position_size > 0")
    lines.append('        strategy.close("Long", comment="Ausstieg")')
    lines.append("    if longEntry and strategy.position_size <= 0")
    lines.append('        strategy.entry("Long", strategy.long)')
    lines.append("")
    lines.append("// Nach dem Zeitfenster wird glattgestellt.")
    lines.append("if not inWindow and strategy.position_size != 0")
    lines.append('    strategy.close_all(comment="Zeitfenster Ende")')
    lines.append("")

    if spec.plots:
        lines.append("// --- Darstellung -----------------------------------------------------")
        lines.extend(spec.plots)
        lines.append("")

    lines.append('bgcolor(strategy.position_size > 0 ? color.new(#5ce1a6, 92) : na, title="Im Markt")')
    lines.append("")

    return "\n".join(lines)


def _interval_label(interval: str) -> str:
    labels = {
        "1m": "1 Minute",
        "5m": "5 Minuten",
        "15m": "15 Minuten",
        "30m": "30 Minuten",
        "1h": "1 Stunde",
        "1d": "1 Tag (D)",
        "1wk": "1 Woche (W)",
        "1mo": "1 Monat (M)",
    }
    return labels.get(interval, interval)


def _filename(key: str, symbol: str) -> str:
    safe_symbol = re.sub(r"[^A-Za-z0-9]", "", resolve(symbol).symbol) or "symbol"
    return f"{key}_{safe_symbol}.pine"


def write_pine_files(
    keys: list[str] | None = None,
    out_dir: str | Path = "pine",
    symbol: str = "ES=F",
    start: pd.Timestamp | dt.datetime | str = "2015-01-01",
    end: pd.Timestamp | dt.datetime | str | None = None,
    interval: str = "1d",
    config: BacktestConfig | None = None,
    params: dict[str, dict] | None = None,
) -> list[Path]:
    """Schreibt fuer jede Strategie eine ``.pine``-Datei.

    Strategien ohne Pine-Fassung werden uebersprungen.

    Returns:
        Die Pfade der geschriebenen Dateien.
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    param_map = params or {}

    written: list[Path] = []
    for key in keys if keys is not None else all_keys(include_benchmarks=True):
        try:
            source = to_pine(
                key,
                symbol=symbol,
                start=start,
                end=end,
                interval=interval,
                config=config,
                **param_map.get(key, {}),
            )
        except ValueError:
            continue  # Strategie ohne Pine-Fassung
        path = directory / _filename(key, symbol)
        path.write_text(source, encoding="utf-8")
        written.append(path)

    return written
