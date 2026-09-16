"""Tests der Dashboard-Endpunkte - ohne echten Netzwerkserver."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backtester.engine.results import json_default
from backtester.server import build_catalog, handle_backtest, handle_pine
from tests.helpers import noisy_bars

BARS = noisy_bars(600, seed=12, drift=0.2)


def fake_load(*args, **kwargs):
    """Ersetzt den Download, damit die Tests offline laufen."""
    return BARS


class CatalogTest(unittest.TestCase):
    def test_contains_everything_the_dashboard_needs(self):
        catalog = build_catalog()
        self.assertEqual(len(catalog["strategies"]), 12)
        self.assertTrue(catalog["providers"])
        self.assertTrue(catalog["instruments"])
        self.assertIn("1d", catalog["intervals"])

    def test_instruments_carry_their_tradingview_ticker(self):
        by_symbol = {i["symbol"]: i for i in build_catalog()["instruments"]}
        self.assertEqual(by_symbol["ES=F"]["tradingview"], "CME_MINI:ES1!")

    def test_is_json_serialisable(self):
        json.dumps(build_catalog(), default=json_default, allow_nan=False)


class BacktestEndpointTest(unittest.TestCase):
    def test_returns_ranked_results_and_a_benchmark(self):
        with patch("backtester.engine.gauntlet.load_bars", fake_load):
            payload = handle_backtest({"symbol": "ES=F", "strategies": ["ema_cross", "golden_cross"]})

        self.assertEqual(len(payload["results"]), 2)
        self.assertIsNotNone(payload["benchmark"])
        self.assertEqual(payload["tradingview"], "CME_MINI:ES1!")
        self.assertTrue(payload["results"][0]["equity"])
        self.assertTrue(payload["results"][0]["drawdown"])

    def test_result_survives_strict_json(self):
        """inf und numpy-Zahlen duerfen den Export nicht sprengen."""
        with patch("backtester.engine.gauntlet.load_bars", fake_load):
            payload = handle_backtest({"symbol": "ES=F"})
        body = json.dumps(payload, default=json_default, allow_nan=False)
        self.assertGreater(len(body), 1000)

    def test_series_are_thinned_out(self):
        with patch("backtester.engine.gauntlet.load_bars", fake_load):
            payload = handle_backtest({"symbol": "ES=F", "strategies": ["ema_cross"]})
        self.assertLessEqual(len(payload["results"][0]["equity"]), 1201)

    def test_rejects_an_empty_selection(self):
        with self.assertRaises(ValueError):
            handle_backtest({"symbol": "ES=F", "strategies": []})

    def test_rejects_unknown_strategies(self):
        with self.assertRaises(ValueError) as caught:
            handle_backtest({"symbol": "ES=F", "strategies": ["ema_cross", "quatsch"]})
        self.assertIn("quatsch", str(caught.exception))

    def test_settings_reach_the_engine(self):
        with patch("backtester.engine.gauntlet.load_bars", fake_load):
            payload = handle_backtest({
                "symbol": "ES=F", "strategies": ["ema_cross"],
                "capital": 25_000, "fee": 0.0, "slippage": 0, "exposure": 0.5,
            })
        self.assertEqual(payload["initial_capital"], 25_000)


class PineEndpointTest(unittest.TestCase):
    def test_returns_source_and_ticker(self):
        payload = handle_pine({"strategy": "supertrend", "symbol": "NQ=F"})
        self.assertTrue(payload["source"].startswith("//@version=6"))
        self.assertEqual(payload["tradingview"], "CME_MINI:NQ1!")

    def test_settings_are_written_into_the_script(self):
        payload = handle_pine({"strategy": "ema_cross", "symbol": "ES=F",
                               "capital": 25_000, "fee": 0.2, "slippage": 3})
        self.assertIn("initial_capital = 25000", payload["source"])
        self.assertIn("commission_value = 0.2", payload["source"])
        self.assertIn("slippage = 3", payload["source"])

    def test_missing_strategy_is_reported(self):
        with self.assertRaises(ValueError):
            handle_pine({"symbol": "ES=F"})

    def test_strategy_without_pine_is_reported(self):
        with self.assertRaises(ValueError):
            handle_pine({"strategy": "random", "symbol": "ES=F"})


if __name__ == "__main__":
    unittest.main()
