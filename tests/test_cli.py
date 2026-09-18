"""Tests der Kommandozeile - Argumente, Ausgaben, Fehlerwege."""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backtester import ideas
from backtester.cli import _config_from_args, _parse_params, build_parser, main
from tests.helpers import noisy_bars

BARS = noisy_bars(500, seed=9, drift=0.2)


def fake_load(*args, **kwargs):
    return BARS


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Fuehrt die CLI aus und faengt die Ausgabe ein."""
    out = io.StringIO()
    err = io.StringIO()
    with patch("backtester.cli.load_bars", fake_load), \
         patch("backtester.engine.gauntlet.load_bars", fake_load), \
         redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


class ParserTest(unittest.TestCase):
    def test_every_command_is_registered(self):
        parser = build_parser()
        for command in ("list", "run", "gauntlet", "pine", "data", "dashboard"):
            with self.subTest(command=command):
                self.assertIsNotNone(parser.parse_args([command] + (["ema_cross"] if command == "run" else [])))

    def test_parameters_are_parsed(self):
        self.assertEqual(_parse_params(["fast=5", "slow=30"]), {"fast": "5", "slow": "30"})
        self.assertEqual(_parse_params(None), {})

    def test_malformed_parameter_is_rejected(self):
        with self.assertRaises(SystemExit):
            _parse_params(["fast"])

    def test_all_help_texts_render(self):
        """argparse formatiert Hilfetexte mit %-Ersetzung.

        Ein einzelnes Prozentzeichen im Text bringt das zum Absturz - unter
        Python 3.14 schon beim Anlegen des Arguments, davor erst beim
        Ausgeben der Hilfe. Dieser Test findet es auf jeder Version.
        """
        parser = build_parser()
        self.assertIn("backtester", parser.format_help())

        subparsers = [
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        self.assertTrue(subparsers, "keine Unterbefehle gefunden")

        seen = set()
        for action in subparsers:
            for name, sub in action.choices.items():
                with self.subTest(command=name):
                    self.assertTrue(sub.format_help())
                    seen.add(name)
        self.assertEqual(
            seen,
            {"list", "run", "gauntlet", "pine", "data", "ideas", "dashboard"},
        )

    def test_config_follows_the_flags(self):
        args = build_parser().parse_args([
            "run", "ema_cross", "--capital", "50000", "--fee", "0.05",
            "--slippage", "3", "--contracts", "2", "--allow-short", "--no-compounding",
        ])
        config = _config_from_args(args)
        self.assertEqual(config.initial_capital, 50_000)
        self.assertEqual(config.fee_pct, 0.05)
        self.assertEqual(config.slippage_ticks, 3)
        self.assertEqual(config.sizing, "contracts")
        self.assertEqual(config.contracts, 2)
        self.assertFalse(config.long_only)
        self.assertFalse(config.compounding)


class CommandTest(unittest.TestCase):
    def test_list_shows_strategies_sources_and_contracts(self):
        code, output = run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertIn("EMA Cross (9/21)", output)
        self.assertIn("Yahoo Finance", output)
        self.assertIn("E-mini S&P 500", output)
        self.assertIn("CME_MINI:ES1!", output)

    def test_run_prints_the_detail_report(self):
        code, output = run_cli(["run", "ema_cross", "--symbol", "ES", "--param", "fast=5"])
        self.assertEqual(code, 0)
        self.assertIn("Netto P/L", output)
        self.assertIn("Profit-Faktor", output)
        self.assertIn("Max Drawdown", output)

    def test_gauntlet_prints_the_leaderboard(self):
        code, output = run_cli(["gauntlet", "ema_cross", "golden_cross", "--symbol", "NQ"])
        self.assertEqual(code, 0)
        self.assertIn("RANGLISTE", output)
        self.assertIn("Sieger:", output)
        self.assertIn("Schlechter als Nichtstun", output)

    def test_gauntlet_writes_csv_and_json(self):
        with TemporaryDirectory() as folder:
            csv_path = Path(folder) / "rangliste.csv"
            json_path = Path(folder) / "lauf.json"
            code, _ = run_cli([
                "gauntlet", "ema_cross", "--symbol", "ES",
                "--csv", str(csv_path), "--json", str(json_path),
            ])
            self.assertEqual(code, 0)
            self.assertIn("net_pnl", csv_path.read_text())
            self.assertIn('"metrics"', json_path.read_text())

    def test_pine_writes_files(self):
        with TemporaryDirectory() as folder:
            code, output = run_cli(["pine", "ema_cross", "supertrend", "--out", folder, "--symbol", "ES"])
            self.assertEqual(code, 0)
            written = sorted(p.name for p in Path(folder).glob("*.pine"))
            self.assertEqual(written, ["ema_cross_ESF.pine", "supertrend_ESF.pine"])
            self.assertIn("Strategie-Tester", output)

    def test_pine_stdout_prints_one_script(self):
        code, output = run_cli(["pine", "ema_cross", "--stdout"])
        self.assertEqual(code, 0)
        self.assertIn("//@version=6", output)

    def test_pine_stdout_needs_exactly_one_strategy(self):
        with self.assertRaises(SystemExit):
            run_cli(["pine", "ema_cross", "golden_cross", "--stdout"])

    def test_data_shows_the_contract_specs(self):
        code, output = run_cli(["data", "--symbol", "ES", "--rows", "3"])
        self.assertEqual(code, 0)
        self.assertIn("Punktwert 50.0 USD", output)
        self.assertIn("CME_MINI:ES1!", output)


class IdeasCommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        patcher = patch.object(ideas, "DEFAULT_DIR", Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_says_so_when_there_is_nothing(self):
        code, output = run_cli(["ideas"])
        self.assertEqual(code, 0)
        self.assertIn("Noch nichts notiert", output)

    def test_lists_notes_with_their_context(self):
        ideas.add("ATR-Stop fuer RSI-2", {
            "symbol": "ES=F", "interval": "1d",
            "strategy_label": "RSI-2 Dip Buy (Connors)",
            "metrics": {"net_pnl": 14039.0, "trades": 95},
        })
        code, output = run_cli(["ideas"])
        self.assertEqual(code, 0)
        self.assertIn("ATR-Stop fuer RSI-2", output)
        self.assertIn("RSI-2 Dip Buy (Connors)", output)
        self.assertIn("ES=F", output)

    def test_open_only_hides_finished_notes(self):
        done = ideas.add("erledigt", None)
        ideas.set_status(done["id"], "erledigt")
        ideas.add("offen", None)
        code, output = run_cli(["ideas", "--open-only"])
        self.assertEqual(code, 0)
        self.assertIn("offen", output)
        self.assertNotIn("erledigt", output)

    def test_prompt_form_is_plain_text(self):
        ideas.add("Naechste Strategie: ORB auf NQ", {"symbol": "NQ=F"})
        code, output = run_cli(["ideas", "--prompt"])
        self.assertEqual(code, 0)
        self.assertIn("Naechste Strategie: ORB auf NQ", output)
        self.assertNotIn("[ ]", output)


class ErrorTest(unittest.TestCase):
    def test_unknown_strategy_exits_with_code_one(self):
        code, output = run_cli(["run", "gibtsnicht"])
        self.assertEqual(code, 1)
        self.assertIn("Unbekannte Strategie", output)

    def test_unknown_parameter_exits_with_code_one(self):
        code, output = run_cli(["run", "ema_cross", "--param", "quatsch=1"])
        self.assertEqual(code, 1)
        self.assertIn("quatsch", output)


if __name__ == "__main__":
    unittest.main()
