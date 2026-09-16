"""Ausgabe fuer das Terminal - die Rangliste im Stil des Dashboards."""

from __future__ import annotations

import os
import sys

from ..engine.gauntlet import GauntletResult
from ..engine.results import BacktestResult

# ANSI-Farben; bei umgeleiteter Ausgabe oder NO_COLOR wird abgeschaltet.
_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


GREEN = lambda t: _c(t, "38;5;42")
RED = lambda t: _c(t, "38;5;167")
GOLD = lambda t: _c(t, "38;5;178")
DIM = lambda t: _c(t, "2")
BOLD = lambda t: _c(t, "1")


def money(value: float) -> str:
    """Formatiert Dollar-Betraege mit Vorzeichen und Tausenderpunkten."""
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


def _colored_money(value: float) -> tuple[str, int]:
    """Gibt den eingefaerbten Text und seine sichtbare Laenge zurueck."""
    plain = money(value)
    return (GREEN(plain) if value >= 0 else RED(plain)), len(plain)


def _pad(text: str, visible_len: int, width: int, align: str = ">") -> str:
    """Padding, das ANSI-Codes nicht mitzaehlt."""
    fill = " " * max(width - visible_len, 0)
    return (fill + text) if align == ">" else (text + fill)


def print_leaderboard(gauntlet: GauntletResult, show_extra: bool = False) -> None:
    """Druckt die Rangliste eines Gauntlet-Laufs."""
    header = (
        f"{'#':<3} {'STRATEGIE':<30} {'NETTO P/L':>13} {'RENDITE':>9} "
        f"{'MAX DD':>8} {'TRADES':>7} {'WIN %':>7} {'PF':>6}"
    )
    if show_extra:
        header += f" {'SHARPE':>7} {'CAGR':>7} {'MARKT':>7}"

    print()
    print(BOLD(f"  RANGLISTE - {gauntlet.symbol} - {gauntlet.interval}"))
    print(
        DIM(
            f"  {gauntlet.start.date()} bis {gauntlet.end.date()}  ·  {gauntlet.bars} Bars  ·  "
            f"Start ${gauntlet.initial_capital:,.0f}".replace(",", ".")
        )
    )
    print()
    print(DIM(header))
    print(DIM("  " + "-" * (len(header) - 2)))

    for rank, result in enumerate(gauntlet.ranked, 1):
        print(_row(str(rank), result, show_extra))

    if gauntlet.benchmark is not None:
        print(DIM("  " + "-" * (len(header) - 2)))
        print(_row("-", gauntlet.benchmark, show_extra, benchmark=True))

    print()
    winner = gauntlet.winner
    if winner is not None:
        print(f"  Sieger:          {BOLD(winner.strategy_label)}  {_colored_money(winner.metrics.net_pnl)[0]}")
    if gauntlet.benchmark is not None:
        beaten = gauntlet.beaten_by_benchmark
        note = f"  Schlechter als Nichtstun:  {beaten} von {len(gauntlet.results)}"
        print(RED(note) if beaten > len(gauntlet.results) / 2 else note)
    if gauntlet.failures:
        print()
        for key, error in gauntlet.failures.items():
            print(RED(f"  Fehler in {key}: {error}"))
    print()


def _row(rank: str, result: BacktestResult, show_extra: bool, benchmark: bool = False) -> str:
    m = result.metrics
    label = result.strategy_label if not benchmark else f"{result.strategy_label} - BENCHMARK"
    pnl_text, pnl_len = _colored_money(m.net_pnl)

    profit_factor = "-" if benchmark or not m.profit_factor else f"{m.profit_factor:.1f}"
    win_rate = "-" if benchmark else f"{m.win_rate_pct:.1f}"

    line = (
        f"{rank:<3} {label[:30]:<30} {_pad(pnl_text, pnl_len, 13)} "
        f"{m.return_pct:>8.1f}% {m.max_drawdown_pct:>7.1f}% {m.trades:>7} "
        f"{win_rate:>7} {profit_factor:>6}"
    )
    if show_extra:
        line += f" {m.sharpe:>7.2f} {m.cagr_pct:>6.1f}% {m.exposure_pct:>6.0f}%"
    return GOLD(line) if benchmark else line


def print_detail(result: BacktestResult) -> None:
    """Druckt den ausfuehrlichen Bericht eines einzelnen Laufs."""
    m = result.metrics
    pnl_text, _ = _colored_money(m.net_pnl)

    print()
    print(BOLD(f"  {result.strategy_label}  -  {result.symbol} {result.interval}"))
    print(DIM(f"  {result.start.date()} bis {result.end.date()}"))
    if result.params:
        print(DIM("  Parameter: " + ", ".join(f"{k}={v}" for k, v in result.params.items())))
    print()

    rows = [
        ("Netto P/L", pnl_text),
        ("Rendite", f"{m.return_pct:.2f} %"),
        ("CAGR", f"{m.cagr_pct:.2f} %"),
        ("Endkapital", f"${m.final_equity:,.0f}".replace(",", ".")),
        ("", ""),
        ("Max Drawdown", f"{m.max_drawdown_pct:.2f} %"),
        ("Laengste Verlustphase", f"{m.longest_drawdown_days} Tage"),
        ("Volatilitaet p.a.", f"{m.volatility_pct:.2f} %"),
        ("Sharpe", f"{m.sharpe:.2f}"),
        ("Sortino", f"{m.sortino:.2f}"),
        ("Calmar", f"{m.calmar:.2f}"),
        ("", ""),
        ("Trades", str(m.trades)),
        ("Trefferquote", f"{m.win_rate_pct:.1f} %"),
        ("Profit-Faktor", f"{m.profit_factor:.2f}"),
        ("Erwartungswert je Trade", money(m.expectancy)),
        ("Durchschnittsgewinn", money(m.avg_win)),
        ("Durchschnittsverlust", money(m.avg_loss)),
        ("Groesster Gewinn", money(m.largest_win)),
        ("Groesster Verlust", money(m.largest_loss)),
        ("Haltedauer (Bars)", f"{m.avg_bars_held:.1f}"),
        ("Zeit im Markt", f"{m.exposure_pct:.1f} %"),
        ("Gebuehren gesamt", f"${m.total_fees:,.0f}".replace(",", ".")),
    ]
    for label, value in rows:
        print("" if not label else f"  {label:<26} {value}")
    print()
