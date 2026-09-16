"""Kommandozeile des Backtesters.

    python -m backtester list                      Strategien und Datenquellen
    python -m backtester run ema_cross --symbol ES Einzelne Strategie
    python -m backtester gauntlet --symbol NQ      Alle gegeneinander
    python -m backtester pine --symbol ES          Pine-Skripte exportieren
    python -m backtester dashboard                 Dashboard im Browser
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .data import DataError, load_bars, provider_infos
from .engine import BacktestConfig, run_backtest, run_gauntlet
from .engine.results import json_default
from .instruments import known_instruments, resolve
from .pine import to_pine, tradingview_symbol, write_pine_files
from .report.terminal import print_detail, print_leaderboard
from .strategies import all_keys, catalog, get as get_strategy


# --- gemeinsame Argumente ------------------------------------------------
def _add_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol", "-s", default="ES=F", help="Ticker, z. B. ES, NQ, SPY (Vorgabe: ES=F)")
    parser.add_argument("--start", default="2015-01-01", help="Startdatum JJJJ-MM-TT")
    parser.add_argument("--end", default=None, help="Enddatum JJJJ-MM-TT (Vorgabe: heute)")
    parser.add_argument("--interval", "-i", default="1d", help="1d, 1h, 15m, 5m, 1m (Vorgabe: 1d)")
    parser.add_argument("--provider", "-p", default="yahoo", help="yahoo, csv, stooq, databento, alpaca")
    parser.add_argument("--no-cache", action="store_true", help="Cache umgehen und neu laden")


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--capital", type=float, default=100_000.0, help="Startkapital (Vorgabe: 100000)")
    parser.add_argument("--fee", type=float, default=0.1, help="Gebuehr je Seite in Prozent (Vorgabe: 0.1)")
    parser.add_argument("--slippage", type=float, default=1.0, help="Slippage in Ticks (Vorgabe: 1)")
    parser.add_argument("--exposure", type=float, default=1.0, help="Kapitalanteil je Position (1.0 = 100 %)")
    parser.add_argument("--contracts", type=float, default=None, help="Feste Kontraktzahl statt Prozentgroesse")
    parser.add_argument("--allow-short", action="store_true", help="Short-Positionen zulassen")
    parser.add_argument("--no-compounding", action="store_true", help="Immer mit dem Startkapital rechnen")


def _config_from_args(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=args.capital,
        fee_pct=args.fee,
        slippage_ticks=args.slippage,
        sizing="contracts" if args.contracts else "equity_pct",
        exposure=args.exposure,
        contracts=args.contracts or 1.0,
        long_only=not args.allow_short,
        compounding=not args.no_compounding,
    )


def _parse_params(pairs: list[str] | None) -> dict:
    """Wandelt ``["fast=5", "slow=30"]`` in ein Parameter-Dict."""
    params: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"Parameter muessen die Form name=wert haben, nicht {pair!r}")
        name, value = pair.split("=", 1)
        params[name.strip()] = value.strip()
    return params


# --- Befehle -------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    print("\n  STRATEGIEN\n")
    for entry in catalog():
        params = ", ".join(f"{p['name']}={p['default']}" for p in entry["params"]) or "-"
        pine = "Pine" if get_strategy(entry["key"]).pine() else "    "
        print(f"  {entry['key']:<22} {entry['label']:<34} [{entry['category']:<14}] {pine}")
        print(f"  {'':<22} {params}")
    print("\n  DATENQUELLEN\n")
    for info in provider_infos():
        key_note = f"benoetigt {info.key_env}" if info.needs_key else "kein Konto noetig"
        print(f"  {info.key:<12} {info.name:<28} ({key_note})")
        print(f"  {'':<12} {info.asset_classes}")
        print(f"  {'':<12} {info.note}\n")
    print("  KONTRAKTE\n")
    for inst in known_instruments():
        tv = tradingview_symbol(inst.symbol)
        print(f"  {inst.symbol:<10} {inst.name:<26} {inst.point_value:>8.0f} USD/Punkt   TradingView: {tv}")
    print()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    params = _parse_params(args.param)
    df = load_bars(
        args.symbol, args.start, args.end, args.interval,
        provider=args.provider, use_cache=not args.no_cache,
    )
    result = run_backtest(
        df, args.strategy, symbol=args.symbol, interval=args.interval, config=config, **params
    )
    print_detail(result)

    if args.trades:
        print(f"  {'EINSTIEG':<12} {'AUSSTIEG':<12} {'KURS EIN':>10} {'KURS AUS':>10} {'NETTO':>12} {'BARS':>6}")
        for trade in result.trades:
            print(
                f"  {trade.entry_time.date()!s:<12} {trade.exit_time.date()!s:<12} "
                f"{trade.entry_price:>10.2f} {trade.exit_price:>10.2f} "
                f"{trade.net_pnl:>12,.0f} {trade.bars_held:>6}"
            )
        print()

    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2, default=json_default), encoding="utf-8")
        print(f"  JSON geschrieben: {args.json}\n")
    return 0


def cmd_gauntlet(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    keys = args.strategies or all_keys()
    result = run_gauntlet(
        symbol=args.symbol,
        strategies=keys,
        start=args.start,
        end=args.end,
        interval=args.interval,
        provider=args.provider,
        config=config,
        use_cache=not args.no_cache,
    )
    print_leaderboard(result, show_extra=args.detail)

    if args.csv:
        result.leaderboard().to_csv(args.csv, index=False)
        print(f"  CSV geschrieben: {args.csv}\n")
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2, default=json_default), encoding="utf-8")
        print(f"  JSON geschrieben: {args.json}\n")
    return 0


def cmd_pine(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    keys = args.strategies or all_keys(include_benchmarks=True)

    if args.stdout:
        if len(keys) != 1:
            raise SystemExit("--stdout geht nur mit genau einer Strategie")
        print(to_pine(keys[0], symbol=args.symbol, start=args.start, end=args.end,
                      interval=args.interval, config=config))
        return 0

    written = write_pine_files(
        keys=keys, out_dir=args.out, symbol=args.symbol, start=args.start,
        end=args.end, interval=args.interval, config=config,
    )
    print(f"\n  {len(written)} Pine-Skripte geschrieben nach {Path(args.out).resolve()}\n")
    for path in written:
        print(f"    {path.name}")
    print(
        f"\n  So geht es weiter in TradingView:\n"
        f"    1. Chart auf {tradingview_symbol(args.symbol)} stellen, Zeiteinheit passend zu {args.interval}\n"
        f"    2. Pine-Editor oeffnen (unten) -> Neu -> Leeres Strategie-Skript\n"
        f"    3. Inhalt einer .pine-Datei einfuegen, 'Zum Chart hinzufuegen'\n"
        f"    4. Reiter 'Strategie-Tester' zeigt die Ergebnisse\n"
    )
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    df = load_bars(
        args.symbol, args.start, args.end, args.interval,
        provider=args.provider, use_cache=not args.no_cache,
    )
    inst = resolve(args.symbol)
    print(f"\n  {inst.symbol} - {inst.name}  ({args.provider}, {args.interval})")
    print(f"  {len(df)} Bars von {df.index[0].date()} bis {df.index[-1].date()}")
    print(f"  Punktwert {inst.point_value} USD  ·  Tick {inst.tick_size}  ·  TradingView {tradingview_symbol(inst.symbol)}\n")
    print(df.tail(args.rows).to_string())
    print()
    if args.csv:
        df.to_csv(args.csv)
        print(f"  CSV geschrieben: {args.csv}\n")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .server import serve

    url = f"http://{args.host}:{args.port}/"
    print(f"\n  Dashboard laeuft auf {url}")
    print("  Beenden mit Strg+C\n")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    serve(host=args.host, port=args.port)
    return 0


# --- Parser --------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtester",
        description="Backtester fuer Trading-Strategien auf echten Marktdaten (ES, NQ und mehr).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  python -m backtester gauntlet --symbol ES --start 2015-01-01\n"
            "  python -m backtester run ema_cross --symbol NQ --param fast=5 --param slow=30\n"
            "  python -m backtester pine --symbol ES --out pine\n"
            "  python -m backtester dashboard\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Strategien, Datenquellen und Kontrakte anzeigen").set_defaults(func=cmd_list)

    run_parser = sub.add_parser("run", help="Eine einzelne Strategie backtesten")
    run_parser.add_argument("strategy", help="Strategie-Key, siehe 'list'")
    run_parser.add_argument("--param", action="append", help="Parameter als name=wert, mehrfach erlaubt")
    run_parser.add_argument("--trades", action="store_true", help="Alle Trades auflisten")
    run_parser.add_argument("--json", help="Ergebnis als JSON speichern")
    _add_data_args(run_parser)
    _add_config_args(run_parser)
    run_parser.set_defaults(func=cmd_run)

    gauntlet_parser = sub.add_parser("gauntlet", help="Mehrere Strategien gegeneinander antreten lassen")
    gauntlet_parser.add_argument("strategies", nargs="*", help="Keys; leer = alle")
    gauntlet_parser.add_argument("--detail", action="store_true", help="Sharpe, CAGR und Marktzeit mit ausgeben")
    gauntlet_parser.add_argument("--csv", help="Rangliste als CSV speichern")
    gauntlet_parser.add_argument("--json", help="Alles als JSON speichern")
    _add_data_args(gauntlet_parser)
    _add_config_args(gauntlet_parser)
    gauntlet_parser.set_defaults(func=cmd_gauntlet)

    pine_parser = sub.add_parser("pine", help="Strategien als TradingView-Pine-Skripte exportieren")
    pine_parser.add_argument("strategies", nargs="*", help="Keys; leer = alle")
    pine_parser.add_argument("--out", default="pine", help="Zielordner (Vorgabe: pine)")
    pine_parser.add_argument("--stdout", action="store_true", help="Skript direkt ausgeben statt speichern")
    _add_data_args(pine_parser)
    _add_config_args(pine_parser)
    pine_parser.set_defaults(func=cmd_pine)

    data_parser = sub.add_parser("data", help="Marktdaten pruefen und exportieren")
    data_parser.add_argument("--rows", type=int, default=10, help="Wie viele Bars anzeigen")
    data_parser.add_argument("--csv", help="Bars als CSV speichern")
    _add_data_args(data_parser)
    data_parser.set_defaults(func=cmd_data)

    dash_parser = sub.add_parser("dashboard", help="Das Dashboard im Browser starten")
    dash_parser.add_argument("--host", default="127.0.0.1")
    dash_parser.add_argument("--port", type=int, default=8000)
    dash_parser.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch oeffnen")
    dash_parser.set_defaults(func=cmd_dashboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DataError as exc:
        print(f"\n  Datenfehler: {exc}\n", file=sys.stderr)
        return 2
    except (KeyError, ValueError) as exc:
        print(f"\n  Fehler: {exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n  Abgebrochen.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
