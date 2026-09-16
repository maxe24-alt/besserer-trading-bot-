"""Tests der Indikatoren gegen von Hand nachrechenbare Werte."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtester import indicators as ta
from tests.helpers import make_bars, noisy_bars


class MovingAverageTest(unittest.TestCase):
    def test_sma_is_the_plain_mean(self):
        series = pd.Series([1.0, 2, 3, 4, 5, 6])
        result = ta.sma(series, 3)
        self.assertTrue(np.isnan(result.iloc[1]))     # Anlaufphase bleibt leer
        self.assertAlmostEqual(result.iloc[2], 2.0)   # (1+2+3)/3
        self.assertAlmostEqual(result.iloc[5], 5.0)   # (4+5+6)/3

    def test_ema_reacts_faster_than_sma(self):
        """Kurz nach einem Sprung liegt die EMA vorn - spaeter holt die SMA auf."""
        series = pd.Series([10.0] * 20 + [20.0] * 3)
        self.assertGreater(ta.ema(series, 10).iloc[-1], ta.sma(series, 10).iloc[-1])

    def test_warmup_is_masked(self):
        series = pd.Series(np.arange(50, dtype=float))
        for length in (5, 20):
            self.assertEqual(int(ta.sma(series, length).isna().sum()), length - 1)
            self.assertEqual(int(ta.ema(series, length).isna().sum()), length - 1)


class OscillatorTest(unittest.TestCase):
    def test_rsi_stays_between_0_and_100(self):
        rsi = ta.rsi(noisy_bars(300)["close"], 14).dropna()
        self.assertTrue((rsi >= 0).all() and (rsi <= 100).all())

    def test_rsi_is_100_when_price_only_rises(self):
        rising = pd.Series(np.arange(100, 160, dtype=float))
        self.assertAlmostEqual(ta.rsi(rising, 14).iloc[-1], 100.0, places=6)

    def test_rsi_is_0_when_price_only_falls(self):
        falling = pd.Series(np.arange(160, 100, -1, dtype=float))
        self.assertAlmostEqual(ta.rsi(falling, 14).iloc[-1], 0.0, places=6)

    def test_stochastic_marks_the_extremes(self):
        bars = make_bars([100.0 + i for i in range(40)])
        percent_k, _ = ta.stochastic(bars, 14, 1, 1)
        self.assertGreater(percent_k.iloc[-1], 95)  # Schluss am Fensterhoch

    def test_macd_histogram_is_the_difference(self):
        close = noisy_bars(200)["close"]
        line, signal, hist = ta.macd(close)
        pd.testing.assert_series_equal(hist.dropna(), (line - signal).dropna())


class VolatilityTest(unittest.TestCase):
    def test_atr_is_positive_and_smoothed(self):
        atr = ta.atr(noisy_bars(200), 14).dropna()
        self.assertTrue((atr > 0).all())
        self.assertLess(atr.std(), noisy_bars(200)["close"].std())

    def test_bollinger_bands_bracket_the_middle(self):
        close = noisy_bars(200)["close"]
        lower, mid, upper = ta.bollinger(close, 20, 2.0)
        valid = mid.notna()
        self.assertTrue((lower[valid] <= mid[valid]).all())
        self.assertTrue((upper[valid] >= mid[valid]).all())


class ChannelTest(unittest.TestCase):
    def test_donchian_excludes_the_current_bar(self):
        """Ohne den Versatz waere ein Ausbruch rechnerisch unmoeglich."""
        bars = make_bars([100.0, 101, 102, 103, 130])
        _, _, upper = ta.donchian(bars, 3)
        self.assertLess(upper.iloc[-1], bars["high"].iloc[-1])

    def test_rolling_high_matches_manual_maximum(self):
        bars = make_bars([10.0, 12, 11, 15, 13, 9])
        highs = ta.rolling_high(bars["high"], 3)
        self.assertAlmostEqual(highs.iloc[3], bars["high"].iloc[0:3].max())

    def test_supertrend_direction_is_only_plus_or_minus_one(self):
        _, direction = ta.supertrend(noisy_bars(300), 10, 3.0)
        self.assertEqual(set(direction.dropna().unique()) - {1.0, -1.0}, set())

    def test_supertrend_stays_long_in_an_uptrend(self):
        bars = make_bars([100.0 + 2 * i for i in range(120)])
        _, direction = ta.supertrend(bars, 10, 3.0)
        self.assertEqual(direction.iloc[-1], 1.0)

    def test_ichimoku_cloud_is_shifted_forward(self):
        bars = noisy_bars(200)
        tenkan, kijun, span_a, span_b = ta.ichimoku(bars, 9, 26, 52)
        # Die Wolkenlinien haben genau kijun Werte mehr in der Anlaufphase.
        self.assertGreater(int(span_a.isna().sum()), int(kijun.isna().sum()))
        self.assertGreaterEqual(int(span_b.isna().sum()), 52 + 26 - 1)


class VwapTest(unittest.TestCase):
    def test_falls_back_to_typical_price_without_volume(self):
        bars = noisy_bars(100)
        bars["volume"] = 0.0
        vwap = ta.rolling_vwap(bars, 20)
        typical = ((bars["high"] + bars["low"] + bars["close"]) / 3).rolling(20, min_periods=20).mean()
        pd.testing.assert_series_equal(vwap.dropna(), typical.dropna(), check_names=False)

    def test_weights_by_volume(self):
        bars = make_bars([100.0, 100, 100, 200])
        bars["volume"] = [1.0, 1.0, 1.0, 1000.0]
        # Das grosse Volumen auf der letzten Bar zieht den VWAP nach oben.
        self.assertGreater(ta.rolling_vwap(bars, 4).iloc[-1], 150)


class CrossTest(unittest.TestCase):
    def test_crossover_fires_exactly_once(self):
        a = pd.Series([1.0, 2, 3, 4, 3, 2])
        b = pd.Series([3.0, 3, 3, 3, 3, 3])
        self.assertEqual(int(ta.crossover(a, b).sum()), 1)
        self.assertEqual(int(ta.crossunder(a, b).sum()), 1)
        self.assertTrue(ta.crossover(a, b).iloc[3])
        # Bei index 4 liegt a genau auf b - gleichauf ist noch kein Schnitt.
        self.assertFalse(ta.crossunder(a, b).iloc[4])
        self.assertTrue(ta.crossunder(a, b).iloc[5])


if __name__ == "__main__":
    unittest.main()
