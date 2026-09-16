"""Tests der Strategien und ihrer Registry."""

from __future__ import annotations

import unittest

import pandas as pd

from backtester.engine import BacktestConfig, run_backtest, run_gauntlet
from backtester.strategies import all_keys, available, catalog, get
from backtester.strategies.base import hold_position, state_position
from tests.helpers import mean_reverting_bars, noisy_bars, trending_bars, wave_bars

FREE = BacktestConfig(fee_pct=0.0, slippage_ticks=0.0, commission_per_contract=0.0)


class RegistryTest(unittest.TestCase):
    def test_twelve_strategies_plus_benchmarks(self):
        self.assertEqual(len(all_keys()), 12)
        self.assertIn("buy_hold", all_keys(include_benchmarks=True))
        self.assertNotIn("buy_hold", all_keys())

    def test_catalog_is_complete(self):
        for entry in catalog(include_benchmarks=True):
            self.assertTrue(entry["key"] and entry["label"] and entry["category"])
            self.assertTrue(entry["description"], f"{entry['key']} hat keine Beschreibung")
            self.assertIsInstance(entry["params"], list)

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(KeyError):
            get("gibt-es-nicht")

    def test_parameters_are_coerced_and_clamped(self):
        strategy = get("ema_cross", fast="7.6", slow=5000)
        self.assertEqual(strategy.settings["fast"], 8)      # gerundet
        self.assertEqual(strategy.settings["slow"], 400)    # auf das Maximum gekappt


class SignalTest(unittest.TestCase):
    def test_every_strategy_produces_clean_signals(self):
        bars = noisy_bars(400)
        for key in all_keys(include_benchmarks=True):
            with self.subTest(strategy=key):
                signals = get(key).signals(bars)
                self.assertEqual(len(signals), len(bars))
                self.assertFalse(signals.isna().any())
                self.assertTrue(set(signals.unique()) <= {-1, 0, 1})

    # MACD ist ein Momentum-Oszillator, kein Trendzustand: auch in einem
    # klaren Aufwaertstrend pendelt die Linie um ihr Signal und er ist nur
    # etwa die Haelfte der Zeit long. Gemessen wird er deshalb am Ertrag.
    TREND_STATE = ("ema_cross", "golden_cross", "supertrend", "turtle_breakout")
    ALL_TREND = TREND_STATE + ("macd_cross", "ichimoku")

    def test_trend_state_strategies_stay_long_in_an_uptrend(self):
        # Lang genug, dass auch die 200er SMA ihre Anlaufphase hinter sich hat.
        bars = trending_bars(1200)
        for key in self.TREND_STATE:
            with self.subTest(strategy=key):
                signals = get(key).signals(bars)
                self.assertGreater((signals > 0).mean(), 0.7, f"{key} verpasst den Trend")

    def test_trend_strategies_earn_in_an_uptrend(self):
        """Gegen einen realistischen Aufwaertstrend - Random Walk mit Drift."""
        for seed in (5, 21, 77):
            bars = noisy_bars(1200, seed=seed, drift=0.35)
            for key in self.ALL_TREND:
                with self.subTest(strategy=key, seed=seed):
                    result = run_backtest(bars, key, symbol="TEST", config=FREE)
                    self.assertGreater(result.metrics.net_pnl, 0,
                                       f"{key} verliert in einem Aufwaertstrend")

    def test_trend_state_strategies_stay_out_of_a_downtrend(self):
        bars = trending_bars(1200, slope=-0.3, start_price=800.0)
        for key in ("ema_cross", "golden_cross", "turtle_breakout"):
            with self.subTest(strategy=key):
                signals = get(key).signals(bars).clip(lower=0)
                self.assertLess((signals > 0).mean(), 0.2, f"{key} bleibt im Abwaertstrend long")

    def test_mean_reversion_earns_in_a_mean_reverting_market(self):
        for key in ("bollinger_reversion", "vwap_reversion"):
            for seed in (3, 11, 42):
                with self.subTest(strategy=key, seed=seed):
                    bars = mean_reverting_bars(800, seed=seed)
                    result = run_backtest(bars, key, symbol="TEST", config=FREE)
                    self.assertGreater(result.metrics.trades, 5)
                    self.assertGreater(result.metrics.net_pnl, 0,
                                       f"{key} verliert in einem Markt, der zum Mittel zurueckkehrt")

    def test_mean_reversion_trades_in_waves_without_breaking(self):
        """Glatte Wellen sind der harte Fall - hier zaehlt nur, dass sauber gehandelt wird."""
        bars = wave_bars(600)
        for key in ("rsi_mean_reversion", "bollinger_reversion", "stochastic_trend"):
            with self.subTest(strategy=key):
                result = run_backtest(bars, key, symbol="TEST", config=FREE)
                self.assertTrue((result.equity > 0).all())
                for entry in result.trades:
                    self.assertLessEqual(entry.entry_time, entry.exit_time)


class PositionHelperTest(unittest.TestCase):
    def test_hold_position_keeps_the_state(self):
        entries = pd.Series([True, False, False, False, False])
        exits = pd.Series([False, False, False, True, False])
        self.assertEqual(list(hold_position(entries, exits)), [1, 1, 1, 0, 0])

    def test_exit_wins_on_a_bar_with_both_signals(self):
        entries = pd.Series([True, True, True])
        exits = pd.Series([False, True, False])
        # Bar 1: erst raus, kein sofortiger Wiedereinstieg.
        self.assertEqual(list(hold_position(entries, exits)), [1, 0, 1])

    def test_state_position_follows_the_condition(self):
        long_on = pd.Series([False, True, True, False])
        short_on = pd.Series([True, False, False, False])
        self.assertEqual(list(state_position(long_on, short_on)), [-1, 1, 1, 0])


class GauntletTest(unittest.TestCase):
    def test_runs_all_strategies_on_the_same_bars(self):
        bars = noisy_bars(500)
        result = run_gauntlet(symbol="ES=F", df=bars, config=FREE)

        self.assertEqual(len(result.results), 12)
        self.assertEqual(result.failures, {})
        self.assertIsNotNone(result.benchmark)
        self.assertEqual(result.bars, len(bars))

        # Rangliste absteigend nach Netto-P/L.
        pnls = [r.metrics.net_pnl for r in result.ranked]
        self.assertEqual(pnls, sorted(pnls, reverse=True))
        self.assertEqual(result.winner.metrics.net_pnl, max(pnls))

    def test_a_broken_strategy_does_not_stop_the_run(self):
        bars = noisy_bars(200)
        result = run_gauntlet(symbol="TEST", df=bars, strategies=["ema_cross", "gibtsnicht"], config=FREE)
        self.assertEqual(len(result.results), 1)
        self.assertIn("gibtsnicht", result.failures)

    def test_leaderboard_frame_has_a_row_per_strategy(self):
        result = run_gauntlet(symbol="TEST", df=noisy_bars(300),
                              strategies=["ema_cross", "golden_cross"], config=FREE)
        frame = result.leaderboard()
        self.assertEqual(len(frame), 3)  # zwei Strategien plus Benchmark
        self.assertIn("net_pnl", frame.columns)


if __name__ == "__main__":
    unittest.main()
