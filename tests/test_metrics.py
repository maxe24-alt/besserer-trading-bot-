"""Tests der Kennzahlen gegen von Hand gerechnete Faelle."""

from __future__ import annotations

import unittest

import pandas as pd

from backtester.engine.metrics import compute_metrics
from backtester.engine.results import Trade, finite_or_none


def trade(net: float, bars: int = 5) -> Trade:
    stamp = pd.Timestamp("2020-01-01", tz="UTC")
    return Trade(
        entry_time=stamp, exit_time=stamp + pd.Timedelta(days=bars), direction=1, units=1.0,
        entry_price=100.0, exit_price=100.0 + net, gross_pnl=net, fees=0.0, net_pnl=net,
        bars_held=bars, return_pct=net,
    )


def curve(values: list[float]) -> pd.Series:
    index = pd.date_range("2020-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=index)


class DrawdownTest(unittest.TestCase):
    def test_max_drawdown_from_the_peak(self):
        # Hoch 120, Tief 90 -> 25 % unter dem Hoch.
        equity = curve([100, 120, 90, 110])
        metrics = compute_metrics(equity, [], equity * 0 + 1, 100.0)
        self.assertAlmostEqual(metrics.max_drawdown_pct, -25.0, places=2)
        self.assertAlmostEqual(metrics.max_drawdown_abs, -30.0, places=2)

    def test_monotone_curve_has_no_drawdown(self):
        equity = curve([100, 110, 120, 130])
        metrics = compute_metrics(equity, [], equity * 0 + 1, 100.0)
        self.assertEqual(metrics.max_drawdown_pct, 0.0)
        self.assertEqual(metrics.longest_drawdown_days, 0)

    def test_longest_underwater_phase_in_days(self):
        # Gezaehlt wird die Zeit UNTER dem alten Hoch: Tag 2 und 3 liegen
        # darunter, an Tag 4 ist die 120 wieder da - also 2 Tage.
        equity = curve([100, 120, 90, 100, 120])
        metrics = compute_metrics(equity, [], equity * 0 + 1, 100.0)
        self.assertEqual(metrics.longest_drawdown_days, 2)


class TradeStatsTest(unittest.TestCase):
    def setUp(self):
        self.trades = [trade(100), trade(-50), trade(200), trade(-25)]
        self.equity = curve([100_000, 100_100, 100_050, 100_250, 100_225])
        self.positions = self.equity * 0 + 1

    def test_win_rate_and_profit_factor(self):
        metrics = compute_metrics(self.equity, self.trades, self.positions, 100_000.0)
        self.assertEqual(metrics.trades, 4)
        self.assertAlmostEqual(metrics.win_rate_pct, 50.0)
        # Gewinne 300, Verluste 75 -> Faktor 4.
        self.assertAlmostEqual(metrics.profit_factor, 4.0)
        self.assertAlmostEqual(metrics.expectancy, 56.25)
        self.assertAlmostEqual(metrics.avg_win, 150.0)
        self.assertAlmostEqual(metrics.avg_loss, -37.5)
        self.assertAlmostEqual(metrics.largest_win, 200.0)
        self.assertAlmostEqual(metrics.largest_loss, -50.0)

    def test_profit_factor_without_losses_is_not_a_number(self):
        winners = [trade(10), trade(20)]
        metrics = compute_metrics(self.equity, winners, self.positions, 100_000.0)
        self.assertEqual(metrics.profit_factor, float("inf"))
        # Fuer JSON und Dashboard wird daraus ein Strich.
        self.assertIsNone(finite_or_none(metrics.profit_factor))

    def test_exposure_counts_bars_in_the_market(self):
        positions = curve([1, 1, 0, 0, 1])
        metrics = compute_metrics(self.equity, [], positions, 100_000.0)
        self.assertAlmostEqual(metrics.exposure_pct, 60.0)


class RatioTest(unittest.TestCase):
    def test_sortino_is_never_below_sharpe(self):
        """Sortino bestraft nur Abwaertsbewegungen - er muss milder ausfallen."""
        equity = curve([100 * (1.01 ** i) + (3 if i % 7 == 0 else 0) for i in range(300)])
        metrics = compute_metrics(equity, [], equity * 0 + 1, 100.0)
        self.assertGreaterEqual(metrics.sortino, metrics.sharpe)

    def test_cagr_of_a_doubling_over_two_years(self):
        index = pd.date_range("2020-01-01", "2022-01-01", freq="D", tz="UTC")
        equity = pd.Series(
            [100_000 * (2 ** (i / (len(index) - 1))) for i in range(len(index))], index=index
        )
        metrics = compute_metrics(equity, [], equity * 0 + 1, 100_000.0)
        self.assertAlmostEqual(metrics.cagr_pct, 41.4, delta=0.5)  # sqrt(2) - 1

    def test_empty_curve_returns_zeros(self):
        metrics = compute_metrics(pd.Series(dtype=float), [], pd.Series(dtype=float), 100_000.0)
        self.assertEqual(metrics.trades, 0)
        self.assertEqual(metrics.net_pnl, 0.0)


if __name__ == "__main__":
    unittest.main()


class ConcentrationTest(unittest.TestCase):
    """Haengt das Ergebnis an einem einzigen Treffer?

    Ein Anteil nahe 100 Prozent heisst: die Regel selbst hat nichts bewiesen,
    das Resultat ist ein Glueckstreffer mit Beiwerk.
    """

    def setUp(self):
        self.equity = curve([100_000] * 5)
        self.positions = self.equity * 0 + 1

    def test_one_trade_carries_everything(self):
        trades = [trade(1000), trade(-20), trade(-30), trade(10)]
        metrics = compute_metrics(curve([100_000, 100_960]), trades, self.positions, 100_000.0)
        # 1000 von 960 netto -> ueber 100 Prozent, weil der Rest zusammen verliert.
        self.assertGreater(metrics.top_trade_share_pct, 100)

    def test_evenly_spread_result(self):
        trades = [trade(250), trade(250), trade(250), trade(250)]
        metrics = compute_metrics(curve([100_000, 101_000]), trades, self.positions, 100_000.0)
        self.assertAlmostEqual(metrics.top_trade_share_pct, 25.0, places=1)

    def test_no_share_without_profit(self):
        trades = [trade(-100), trade(-50)]
        metrics = compute_metrics(curve([100_000, 99_850]), trades, self.positions, 100_000.0)
        self.assertEqual(metrics.top_trade_share_pct, 0.0)
