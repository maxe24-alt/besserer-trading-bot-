"""Tests der Backtest-Engine - vor allem: keine Blicke in die Zukunft."""

from __future__ import annotations

import unittest

import pandas as pd

from backtester.engine import BacktestConfig, run_backtest
from backtester.strategies import get
from tests.helpers import make_bars, trending_bars


# Voellig kostenfrei - auch die Kontraktkommission, die sonst aus der
# Instrumentspezifikation kommt (ES=F: 2,25 USD je Kontrakt und Seite).
FREE = BacktestConfig(fee_pct=0.0, slippage_ticks=0.0, commission_per_contract=0.0)


class BuyAndHoldTest(unittest.TestCase):
    """Buy & Hold ist die Messlatte: das Ergebnis muss exakt nachrechenbar sein."""

    def test_matches_price_move_exactly(self):
        bars = trending_bars(periods=200)
        result = run_backtest(bars, "buy_hold", symbol="TEST", config=FREE)

        # Das Signal von Bar 0 wird zur Eroeffnung von Bar 1 ausgefuehrt.
        expected = 100_000.0 * bars["close"].iloc[-1] / bars["open"].iloc[1]
        self.assertAlmostEqual(result.metrics.final_equity, expected, places=0)
        self.assertEqual(result.metrics.trades, 1)
        self.assertAlmostEqual(result.metrics.exposure_pct, 99.5, places=1)

    def test_futures_multiplier_scales_profit(self):
        """Bei gleichem Einsatz ist der Punktwert egal - er kuerzt sich heraus."""
        bars = trending_bars(periods=120)
        as_stock = run_backtest(bars, "buy_hold", symbol="UNBEKANNT", config=FREE)
        as_future = run_backtest(bars, "buy_hold", symbol="ES=F", config=FREE)
        self.assertAlmostEqual(as_stock.metrics.net_pnl, as_future.metrics.net_pnl, places=0)

    def test_fixed_contracts_uses_point_value(self):
        """Mit fester Kontraktzahl schlaegt der Punktwert dagegen voll durch."""
        bars = trending_bars(periods=120)
        config = BacktestConfig(fee_pct=0.0, slippage_ticks=0.0, commission_per_contract=0.0,
                                sizing="contracts", contracts=1)
        result = run_backtest(bars, "buy_hold", symbol="ES=F", config=config)

        points = bars["close"].iloc[-1] - bars["open"].iloc[1]
        self.assertAlmostEqual(result.metrics.net_pnl, points * 50.0, places=2)


class NoLookaheadTest(unittest.TestCase):
    """Der Kern der Engine: gehandelt wird immer erst eine Bar spaeter."""

    def test_entry_fills_at_next_bar_open(self):
        # Kurse steigen ab Bar 10 sprunghaft; der EMA-Cross reagiert danach.
        closes = [100.0] * 10 + [100.0 + 5 * i for i in range(1, 40)]
        bars = make_bars(closes)

        result = run_backtest(bars, "ema_cross", symbol="TEST", config=FREE, fast=2, slow=4)
        self.assertGreater(len(result.trades), 0)

        signals = get("ema_cross", fast=2, slow=4).signals(bars)
        for trade in result.trades:
            entry_index = bars.index.get_loc(trade.entry_time)
            # Das ausloesende Signal stand an der Bar davor.
            self.assertGreater(entry_index, 0)
            self.assertEqual(signals.iloc[entry_index - 1], trade.direction)
            # Und gefuellt wurde zur Eroeffnung, nicht zum Schluss.
            self.assertAlmostEqual(trade.entry_price, bars["open"].iloc[entry_index], places=6)

    def test_signal_on_last_bar_cannot_trade(self):
        """Ein Signal auf der allerletzten Bar darf keinen Trade mehr erzeugen."""
        closes = [100.0] * 30 + [180.0]
        bars = make_bars(closes)
        result = run_backtest(bars, "turtle_breakout", symbol="TEST", config=FREE, entry=5, exit=3)
        self.assertEqual(result.metrics.trades, 0)


class CostTest(unittest.TestCase):
    def test_fees_and_slippage_reduce_result(self):
        bars = trending_bars(periods=250)
        free = run_backtest(bars, "ema_cross", symbol="ES=F", config=FREE)
        costly = run_backtest(
            bars, "ema_cross", symbol="ES=F",
            config=BacktestConfig(fee_pct=0.1, slippage_ticks=2, commission_per_contract=2.25),
        )
        self.assertLess(costly.metrics.net_pnl, free.metrics.net_pnl)
        self.assertGreater(costly.metrics.total_fees, 0)

    def test_without_trades_capital_is_untouched(self):
        bars = trending_bars(periods=60)
        # Fenster viel groesser als die Datenreihe -> kein Signal moeglich.
        result = run_backtest(bars, "high_52w", symbol="TEST", config=FREE, lookback=1000, exit=500)
        self.assertEqual(result.metrics.trades, 0)
        self.assertAlmostEqual(result.metrics.final_equity, 100_000.0, places=6)
        self.assertEqual(result.metrics.max_drawdown_pct, 0.0)


class PositionAccountingTest(unittest.TestCase):
    def test_equity_curve_has_no_gaps(self):
        bars = trending_bars(periods=150)
        result = run_backtest(bars, "ema_cross", symbol="ES=F", config=FREE)
        self.assertEqual(len(result.equity), len(bars))
        self.assertFalse(result.equity.isna().any())
        self.assertTrue((result.equity > 0).all())

    def test_open_position_is_closed_at_the_end(self):
        bars = trending_bars(periods=200)
        result = run_backtest(bars, "buy_hold", symbol="TEST", config=FREE)
        self.assertEqual(result.trades[-1].exit_reason, "end-of-data")
        self.assertEqual(result.trades[-1].exit_time, bars.index[-1])

    def test_long_only_ignores_short_signals(self):
        bars = trending_bars(periods=200, slope=-0.4, start_price=200.0)
        long_only = run_backtest(bars, "ema_cross", symbol="TEST",
                                 config=BacktestConfig(fee_pct=0.0, slippage_ticks=0.0,
                                                       commission_per_contract=0.0, long_only=True))
        self.assertTrue((long_only.positions >= 0).all())

        with_shorts = run_backtest(bars, "ema_cross", symbol="TEST",
                                   config=BacktestConfig(fee_pct=0.0, slippage_ticks=0.0,
                                                         commission_per_contract=0.0, long_only=False))
        self.assertTrue((with_shorts.positions < 0).any())
        # Im Abwaertstrend muessen Shorts das bessere Ergebnis liefern.
        self.assertGreater(with_shorts.metrics.net_pnl, long_only.metrics.net_pnl)


class ValidationTest(unittest.TestCase):
    def test_rejects_impossible_config(self):
        bars = trending_bars(periods=50)
        for bad in (
            BacktestConfig(initial_capital=0),
            BacktestConfig(sizing="zufall"),
            BacktestConfig(fee_pct=-1),
        ):
            with self.assertRaises(ValueError):
                run_backtest(bars, "buy_hold", symbol="TEST", config=bad)

    def test_rejects_too_short_series(self):
        with self.assertRaises(ValueError):
            run_backtest(make_bars([100.0]), "buy_hold", symbol="TEST")

    def test_unknown_strategy_parameter_is_reported(self):
        with self.assertRaises(ValueError):
            get("ema_cross", gibtsnicht=5)


if __name__ == "__main__":
    unittest.main()
