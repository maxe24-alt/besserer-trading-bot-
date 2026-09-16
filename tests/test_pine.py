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
                # Gleiche Kosten und gleiche Positionsgroesse.
                self.assertIn("initial_capital = 50000", source)
                self.assertIn("commission_value = 0.05", source)
                self.assertIn("slippage = 2", source)
                self.assertIn("default_qty_type = strategy.percent_of_equity", source)
                self.assertIn("default_qty_value = 100.0", source)
                # Nur long, kein Pyramidisieren.
                self.assertIn("pyramiding = 0", source)
                self.assertNotIn("strategy.short", source)

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
