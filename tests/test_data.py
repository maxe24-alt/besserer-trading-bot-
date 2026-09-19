"""Tests der Datenschicht - Normalisierung, Cache, CSV, Registry."""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from backtester.data import DataError, bars_per_year, load_bars, normalize_frame, provider_infos, to_utc
from backtester.data import cache
from backtester.data.csv_provider import CsvProvider
from backtester.instruments import canonical_symbol, resolve
from tests.helpers import make_bars


class NormalizeTest(unittest.TestCase):
    def test_accepts_common_column_names(self):
        raw = pd.DataFrame({
            "Date": ["2020-01-01", "2020-01-02"],
            "Open": [10.0, 11], "High": [12.0, 13], "Low": [9.0, 10],
            "Close": [11.0, 12], "Volume": [100, 200],
        })
        frame = normalize_frame(raw)
        self.assertEqual(list(frame.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(str(frame.index.tz), "UTC")

    def test_accepts_short_column_names(self):
        raw = pd.DataFrame({
            "t": ["2020-01-01"], "o": [10.0], "h": [12.0], "l": [9.0], "c": [11.0], "v": [5],
        })
        self.assertEqual(len(normalize_frame(raw)), 1)

    def test_missing_volume_becomes_zero(self):
        raw = pd.DataFrame({"date": ["2020-01-01"], "open": [1.0], "high": [2.0],
                            "low": [0.5], "close": [1.5]})
        self.assertEqual(normalize_frame(raw)["volume"].iloc[0], 0.0)

    def test_drops_gaps_duplicates_and_nonsense(self):
        raw = pd.DataFrame({
            "date": ["2020-01-01", "2020-01-02", "2020-01-02", "2020-01-03", "2020-01-04"],
            "open": [10.0, 11, 11, 12, 13],
            "high": [12.0, 13, 13, 5, 14],      # Zeile 4: High unter Low
            "low": [9.0, 10, 10, 11, 12],
            "close": [11.0, np.nan, 12, 12.5, -1],  # Luecke und negativer Kurs
        })
        frame = normalize_frame(raw)
        self.assertEqual(len(frame), 2)                      # 1. Januar und der 2. (letzter Eintrag)
        self.assertTrue(frame.index.is_monotonic_increasing)
        self.assertFalse(frame.index.duplicated().any())

    def test_missing_price_column_is_reported(self):
        with self.assertRaises(DataError):
            normalize_frame(pd.DataFrame({"date": ["2020-01-01"], "close": [1.0]}))

    def test_empty_frame_is_reported(self):
        with self.assertRaises(DataError):
            normalize_frame(pd.DataFrame())


class TimezoneTest(unittest.TestCase):
    def test_naive_and_aware_both_become_utc(self):
        for value in ("2020-01-01", dt.datetime(2020, 1, 1), pd.Timestamp("2020-01-01", tz="UTC")):
            self.assertEqual(str(to_utc(value).tz), "UTC")

    def test_other_timezones_are_converted(self):
        berlin = pd.Timestamp("2020-06-01 12:00", tz="Europe/Berlin")
        self.assertEqual(to_utc(berlin).hour, 10)  # MESZ ist UTC+2


class BarsPerYearTest(unittest.TestCase):
    """Die Annualisierung muss zum Markt passen.

    Eine Boerse handelt an rund 252 Tagen im Jahr, Krypto an 365. Mit der
    falschen Zahl liegen Sharpe und Volatilitaet um rund 20 Prozent daneben.
    """

    def test_exchange_hours_use_252_days(self):
        # Geschaeftstage, also ohne Wochenende - wie bei ES, NQ oder SPY.
        self.assertEqual(bars_per_year(make_bars([100.0] * 300, freq="B")), 252.0)

    def test_weekend_markets_use_365_days(self):
        # Durchgehende Kalendertage - wie bei Krypto.
        self.assertEqual(bars_per_year(make_bars([100.0] * 300, freq="D")), 365.0)

    def test_weekly_bars(self):
        self.assertEqual(bars_per_year(make_bars([100.0] * 60, freq="W")), 52.0)

    def test_hourly_bars_scale_with_the_trading_day(self):
        frame = make_bars([100.0] * 240, freq="h")
        self.assertGreater(bars_per_year(frame), 252.0)


class CsvProviderTest(unittest.TestCase):
    def test_reads_a_file_from_the_directory(self):
        with TemporaryDirectory() as folder:
            make_bars([100.0, 101, 102]).to_csv(Path(folder) / "ESF_1d.csv")
            frame = CsvProvider(folder).fetch(
                "ES=F", dt.datetime(2019, 1, 1), dt.datetime(2021, 1, 1), "1d"
            )
            self.assertEqual(len(frame), 3)

    def test_reads_a_direct_file_path(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "beliebig.csv"
            make_bars([100.0, 101]).to_csv(path)
            frame = CsvProvider(folder).fetch(
                str(path), dt.datetime(2019, 1, 1), dt.datetime(2021, 1, 1), "1d"
            )
            self.assertEqual(len(frame), 2)

    def test_missing_file_names_the_search_path(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(DataError) as caught:
                CsvProvider(folder).fetch("NQ=F", dt.datetime(2019, 1, 1), dt.datetime(2021, 1, 1))
            self.assertIn("NQF", str(caught.exception))


class CacheTest(unittest.TestCase):
    def test_round_trip(self):
        with TemporaryDirectory() as folder:
            frame = make_bars([100.0 + i for i in range(30)])
            cache.write("test", "ES=F", "1d", frame, cache_dir=folder)
            loaded = cache.read("test", "ES=F", "1d", frame.index[0], frame.index[-1], cache_dir=folder)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded), len(frame))

    def test_misses_when_the_range_is_not_covered(self):
        with TemporaryDirectory() as folder:
            frame = make_bars([100.0] * 10, start="2020-01-01")
            cache.write("test", "ES=F", "1d", frame, cache_dir=folder)
            missed = cache.read(
                "test", "ES=F", "1d",
                pd.Timestamp("2015-01-01", tz="UTC"), pd.Timestamp("2020-01-10", tz="UTC"),
                cache_dir=folder,
            )
            self.assertIsNone(missed)

    def test_writes_merge_instead_of_overwriting(self):
        with TemporaryDirectory() as folder:
            cache.write("test", "ES=F", "1d", make_bars([100.0] * 10, start="2020-01-01"), cache_dir=folder)
            cache.write("test", "ES=F", "1d", make_bars([110.0] * 10, start="2020-01-11"), cache_dir=folder)
            merged = pd.read_csv(cache.cache_path("test", "ES=F", "1d", folder), index_col=0)
            self.assertEqual(len(merged), 20)

    def test_clear_removes_the_files(self):
        with TemporaryDirectory() as folder:
            cache.write("test", "ES=F", "1d", make_bars([100.0] * 5), cache_dir=folder)
            self.assertEqual(cache.clear(folder), 1)


class RegistryTest(unittest.TestCase):
    def test_all_providers_describe_themselves(self):
        for info in provider_infos():
            with self.subTest(provider=info.key):
                self.assertTrue(info.name and info.asset_classes and info.note)
                if info.needs_key:
                    self.assertTrue(info.key_env, f"{info.key}: Umgebungsvariable fehlt")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(DataError):
            load_bars("ES=F", "2020-01-01", "2021-01-01", provider="gibtsnicht")

    def test_reversed_date_range_is_rejected(self):
        with self.assertRaises(DataError):
            load_bars("ES=F", "2021-01-01", "2020-01-01")


class InstrumentTest(unittest.TestCase):
    def test_short_names_resolve(self):
        self.assertEqual(canonical_symbol("es"), "ES=F")
        self.assertEqual(canonical_symbol("NQ"), "NQ=F")

    def test_point_values_are_the_cme_specs(self):
        self.assertEqual(resolve("ES").point_value, 50.0)
        self.assertEqual(resolve("NQ").point_value, 20.0)
        self.assertEqual(resolve("MES").point_value, 5.0)
        self.assertEqual(resolve("MNQ").point_value, 2.0)
        self.assertEqual(resolve("ES").tick_value, 12.5)

    def test_unknown_symbol_behaves_like_a_share(self):
        unknown = resolve("IRGENDWAS")
        self.assertEqual(unknown.point_value, 1.0)
        self.assertEqual(unknown.kind, "stock")


if __name__ == "__main__":
    unittest.main()
