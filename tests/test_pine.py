"""Tests des Pine-Script-Exports.

Kompilieren laesst sich Pine nur in TradingView; hier wird deshalb die
Struktur geprueft - Version, Klammern, Platzhalter, und vor allem, dass die
Ausfuehrungsregeln zum Python-Modell passen.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backtester.engine import BacktestConfig
from backtester.pine import TRADINGVIEW_SYMBOLS, to_pine, tradingview_symbol, write_pine_files
from backtester.strategies import all_keys, get

PINE_KEYS = [k for k in all_keys(include_benchmarks=True) if get(k).pine() is not None]


class CoverageTest(unittest.TestCase):
    def test_every_regular_strategy_has_a_pine_version(self):
        for key in all_keys():
            with self.subTest(strategy=key):
                self.assertIsNotNone(get(key).pine(), f"{key} fehlt die Pine-Fassung")

    def test_strategy_without_pine_is_rejected_clearly(self):
        with self.assertRaises(ValueError):
            to_pine("random")


class StructureTest(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(initial_capital=50_000, fee_pct=0.05, slippage_ticks=2)
        self.sources = {
            key: to_pine(key, symbol="ES=F", start="2018-01-01", end="2026-01-01", config=self.config)
            for key in PINE_KEYS
        }

    def test_header_and_strategy_call(self):
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                self.assertTrue(source.startswith("//@version=6"))
                self.assertIn("strategy(", source)
                self.assertIn("currency = currency.USD)", source)

    def test_no_placeholder_survives(self):
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                self.assertIsNone(re.search(r"\{[a-z_]+\}", source), "unersetzter Platzhalter")

    def test_brackets_and_quotes_are_balanced(self):
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                self.assertEqual(source.count("("), source.count(")"))
                self.assertEqual(source.count("["), source.count("]"))
                self.assertEqual(source.count('"') % 2, 0)

    def test_execution_model_matches_the_python_engine(self):
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                # Ausfuehrung zur naechsten Eroeffnung, nicht zum Schluss.
                self.assertIn("process_orders_on_close = false", source)
                # Gleiche Kosten.
                self.assertIn("initial_capital = 50000", source)
                self.assertIn("commission_value = 0.05", source)
                self.assertIn("slippage = 2", source)
                # Nur long, kein Pyramidisieren.
                self.assertIn("pyramiding = 0", source)
                self.assertNotIn("strategy.short", source)

    def test_time_window_is_off_by_default(self):
        """Sonst klammert ein Enddatum in der Vergangenheit die neuesten Bars aus.

        Auf einer kurzen Zeiteinheit bleibt dann womoeglich kein einziger Bar
        uebrig und der Strategie-Tester zeigt gar kein Ergebnis.
        """
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                self.assertIn('useWindow = input.bool(false,', source)
                self.assertIn("inWindow = not useWindow or (time >= startDate and time <= endDate)", source)
                self.assertIn("if useWindow and not inWindow", source)


    def test_exit_is_checked_before_entry(self):
        """Wie in hold_position: an einer Bar mit beiden Signalen wird verkauft."""
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                exit_at = source.index("if longExit and strategy.position_size > 0")
                entry_at = source.index("if longEntry and strategy.position_size <= 0")
                self.assertLess(exit_at, entry_at)

    def test_every_variable_in_the_rules_is_defined(self):
        keywords = {"and", "or", "not", "true", "false", "close", "open", "high", "low",
                    "volume", "hlc3", "na", "math", "ta"}
        for key, source in self.sources.items():
            with self.subTest(strategy=key):
                assigned = set()
                for group, single in re.findall(r"^\s*(?:\[([\w, ]+)\]|(\w+))\s*=(?!=)", source, re.M):
                    assigned |= {n.strip() for n in group.split(",")} if group else {single}
                for rule in re.findall(r"^(?:longEntry|longExit) = (.+)$", source, re.M):
                    # Namespaces wie ta.crossover fallen raus, nur blanke Namen zaehlen.
                    bare = re.sub(r"\b\w+\.\w+", " ", rule)
                    for token in re.findall(r"\b[a-zA-Z_]\w*\b", bare):
                        if token not in keywords:
                            self.assertIn(token, assigned, f"{key}: {token} ist nirgends definiert")

    def test_parameters_land_in_the_inputs(self):
        source = to_pine("ema_cross", fast=7, slow=34)
        self.assertIn('input.int(7, "Schnelle EMA"', source)
        self.assertIn('input.int(34, "Langsame EMA"', source)

    def test_time_window_is_taken_from_the_arguments(self):
        source = to_pine("ema_cross", start="2021-03-05", end="2024-11-20")
        self.assertIn('timestamp("05 Mar 2021 00:00 +0000")', source)
        self.assertIn('timestamp("20 Nov 2024 00:00 +0000")', source)


class PositionSizeTest(unittest.TestCase):
    """Futures brauchen eine Groesse in Kontrakten.

    Ein NQ-Kontrakt entspricht rund 600.000 USD, ein ES-Kontrakt rund
    385.000 USD. "100 % des Kapitals" ergibt bei 100.000 USD Startkapital
    weniger als einen ganzen Kontrakt - TradingView rundet auf null ab und
    fuehrt keinen einzigen Trade aus.
    """

    FUTURES = ("ES=F", "NQ=F", "MES=F", "MNQ=F", "GC=F", "CL=F")
    NON_FUTURES = ("SPY", "QQQ", "BTC-USD", "AAPL")

    def test_futures_trade_a_fixed_contract_count(self):
        for symbol in self.FUTURES:
            with self.subTest(symbol=symbol):
                source = to_pine("ema_cross", symbol=symbol)
                self.assertIn("default_qty_type = strategy.fixed", source)
                self.assertIn("default_qty_value = 1,", source)
                self.assertIn('contracts = input.float(1, "Kontrakte je Trade"', source)
                self.assertIn('strategy.entry("Long", strategy.long, qty = contracts)', source)
                self.assertNotIn("percent_of_equity", source)

    def test_shares_and_crypto_keep_percent_of_equity(self):
        for symbol in self.NON_FUTURES:
            with self.subTest(symbol=symbol):
                source = to_pine("ema_cross", symbol=symbol)
                self.assertIn("default_qty_type = strategy.percent_of_equity", source)
                self.assertIn("default_qty_value = 100.0", source)
                self.assertIn('strategy.entry("Long", strategy.long)', source)
                self.assertNotIn("strategy.fixed", source)

    def test_explicit_contract_count_is_carried_over(self):
        config = BacktestConfig(sizing="contracts", contracts=3)
        for symbol in ("ES=F", "SPY"):
            with self.subTest(symbol=symbol):
                source = to_pine("ema_cross", symbol=symbol, config=config)
                self.assertIn("default_qty_type = strategy.fixed", source)
                self.assertIn("default_qty_value = 3,", source)
                self.assertIn("--contracts 3", source)

    def test_header_names_the_matching_python_command(self):
        source = to_pine("golden_cross", symbol="NQ=F")
        self.assertIn("--symbol NQ=F --contracts 1", source)
        self.assertIn("E-mini Nasdaq 100, 20 USD je Punkt", source)

    def test_contract_counts_have_no_trailing_decimals(self):
        source = to_pine("ema_cross", symbol="ES=F")
        self.assertNotIn("default_qty_value = 1.0", source)
        self.assertNotIn("--contracts 1.0", source)


class SymbolTest(unittest.TestCase):
    def test_futures_map_to_their_tradingview_tickers(self):
        self.assertEqual(tradingview_symbol("ES"), "CME_MINI:ES1!")
        self.assertEqual(tradingview_symbol("NQ=F"), "CME_MINI:NQ1!")
        self.assertEqual(tradingview_symbol("MNQ"), "CME_MINI:MNQ1!")

    def test_unknown_symbol_is_passed_through(self):
        self.assertEqual(tradingview_symbol("AAPL"), "AAPL")

    def test_every_mapped_symbol_names_an_exchange(self):
        for symbol, ticker in TRADINGVIEW_SYMBOLS.items():
            with self.subTest(symbol=symbol):
                self.assertIn(":", ticker)


class FileExportTest(unittest.TestCase):
    def test_writes_one_file_per_strategy(self):
        with TemporaryDirectory() as folder:
            written = write_pine_files(out_dir=folder, symbol="NQ=F")
            self.assertEqual(len(written), len(PINE_KEYS))
            for path in written:
                self.assertTrue(path.name.endswith("_NQF.pine"))
                self.assertIn("CME_MINI:NQ1!", path.read_text(encoding="utf-8"))

    def test_skips_strategies_without_pine(self):
        with TemporaryDirectory() as folder:
            written = write_pine_files(keys=["ema_cross", "random"], out_dir=folder)
            self.assertEqual([p.stem for p in written], ["ema_cross_ESF"])


if __name__ == "__main__":
    unittest.main()
