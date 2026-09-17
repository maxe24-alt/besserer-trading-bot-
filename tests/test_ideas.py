"""Tests des Notizbuchs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backtester import ideas
from backtester.ideas import IdeaError

CONTEXT = {
    "symbol": "ES=F", "interval": "1d", "start": "2015-01-01", "end": "2026-09-01",
    "strategy": "rsi2_dip", "strategy_label": "RSI-2 Dip Buy (Connors)",
    "params": {"rsi_length": 2, "entry_level": 10},
    "metrics": {"net_pnl": 14039.0, "return_pct": 14.0, "max_drawdown_pct": -19.5,
                "trades": 95, "profit_factor": 1.31},
    "settings": {"capital": 100000, "fee": 0.1, "slippage": 1, "allow_short": False},
}


class StoreTest(unittest.TestCase):
    def test_add_and_load_newest_first(self):
        with TemporaryDirectory() as folder:
            ideas.add("erste", directory=folder)
            ideas.add("zweite", directory=folder)
            entries = ideas.load(folder)
            self.assertEqual([e["text"] for e in entries], ["zweite", "erste"])
            self.assertEqual(entries[0]["status"], "offen")

    def test_ids_come_from_the_server_and_are_unique(self):
        with TemporaryDirectory() as folder:
            # Auch eine mitgeschickte ID wird ignoriert.
            first = ideas.add("a", {"id": "gefaelscht"}, directory=folder)
            second = ideas.add("b", directory=folder)
            self.assertNotEqual(first["id"], "gefaelscht")
            self.assertNotEqual(first["id"], second["id"])

    def test_writes_json_and_markdown(self):
        with TemporaryDirectory() as folder:
            ideas.add("Notiz mit Kontext", CONTEXT, directory=folder)
            base = Path(folder)
            self.assertTrue((base / "ideen.json").is_file())
            markdown = (base / "ideen.md").read_text(encoding="utf-8")
            self.assertIn("Notiz mit Kontext", markdown)
            self.assertIn("RSI-2 Dip Buy (Connors)", markdown)
            self.assertIn("ES=F", markdown)

    def test_empty_text_is_rejected(self):
        with TemporaryDirectory() as folder:
            for bad in ("", "   ", "\n\t"):
                with self.assertRaises(IdeaError):
                    ideas.add(bad, directory=folder)

    def test_overlong_text_is_rejected(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(IdeaError):
                ideas.add("x" * (ideas.MAX_TEXT_LENGTH + 1), directory=folder)

    def test_status_round_trip(self):
        with TemporaryDirectory() as folder:
            entry = ideas.add("Notiz", directory=folder)
            ideas.set_status(entry["id"], "erledigt", directory=folder)
            self.assertEqual(ideas.load(folder)[0]["status"], "erledigt")
            ideas.set_status(entry["id"], "offen", directory=folder)
            self.assertEqual(ideas.load(folder)[0]["status"], "offen")

    def test_invalid_status_is_rejected(self):
        with TemporaryDirectory() as folder:
            entry = ideas.add("Notiz", directory=folder)
            with self.assertRaises(IdeaError):
                ideas.set_status(entry["id"], "vielleicht", directory=folder)

    def test_remove(self):
        with TemporaryDirectory() as folder:
            entry = ideas.add("weg damit", directory=folder)
            ideas.remove(entry["id"], directory=folder)
            self.assertEqual(ideas.load(folder), [])

    def test_unknown_id_is_reported(self):
        with TemporaryDirectory() as folder:
            for call in (lambda: ideas.remove("gibtsnicht", directory=folder),
                         lambda: ideas.set_status("gibtsnicht", "offen", directory=folder)):
                with self.assertRaises(IdeaError):
                    call()

    def test_missing_or_broken_file_returns_empty(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(ideas.load(folder), [])
            Path(folder, "ideen.json").write_text("{kein json", encoding="utf-8")
            self.assertEqual(ideas.load(folder), [])


class ContextFilterTest(unittest.TestCase):
    """Der Browser darf nur bekannte Felder in die Datei schreiben."""

    def test_keeps_the_known_fields(self):
        with TemporaryDirectory() as folder:
            context = ideas.add("Notiz", CONTEXT, directory=folder)["context"]
            self.assertEqual(context["symbol"], "ES=F")
            self.assertEqual(context["strategy_label"], "RSI-2 Dip Buy (Connors)")
            self.assertEqual(context["metrics"]["trades"], 95)
            self.assertEqual(context["params"]["rsi_length"], 2)

    def test_drops_everything_else(self):
        with TemporaryDirectory() as folder:
            context = ideas.add("Notiz", {
                "symbol": "ES=F",
                "eingeschleust": "boese",
                "metrics": {"net_pnl": 1.0, "heimlich": "boese"},
                "settings": {"capital": 1000, "token": "geheim"},
            }, directory=folder)["context"]
            self.assertNotIn("eingeschleust", context)
            self.assertNotIn("heimlich", context["metrics"])
            self.assertNotIn("token", context["settings"])

    def test_no_context_is_fine(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(ideas.add("ohne Kontext", None, directory=folder)["context"], {})
            self.assertEqual(ideas.add("falscher Typ", "quatsch", directory=folder)["context"], {})

    def test_long_strings_are_truncated(self):
        with TemporaryDirectory() as folder:
            context = ideas.add("Notiz", {"symbol": "X" * 500}, directory=folder)["context"]
            self.assertLessEqual(len(context["symbol"]), 120)


class RenderTest(unittest.TestCase):
    def test_markdown_without_entries(self):
        self.assertIn("Noch nichts notiert", ideas.to_markdown([]))

    def test_markdown_counts_open_and_done(self):
        entries = [
            {"id": "a", "created": "2026-09-17T10:00:00+00:00", "status": "offen", "text": "A"},
            {"id": "b", "created": "2026-09-17T09:00:00+00:00", "status": "erledigt", "text": "B"},
        ]
        markdown = ideas.to_markdown(entries)
        self.assertIn("**1 offen**, 1 erledigt.", markdown)
        self.assertIn("## [ ] 2026-09-17", markdown)
        self.assertIn("## [x] 2026-09-17", markdown)

    def test_prompt_carries_text_and_context(self):
        with TemporaryDirectory() as folder:
            entry = ideas.add("ATR-Stop einbauen", CONTEXT, directory=folder)
            prompt = ideas.to_prompt(entry)
            self.assertTrue(prompt.startswith("ATR-Stop einbauen"))
            self.assertIn("RSI-2 Dip Buy (Connors)", prompt)
            self.assertIn("95 Trades", prompt)
            self.assertNotIn(">", prompt)  # Markdown-Zitatzeichen gehoeren nicht in den Prompt


class EndpointTest(unittest.TestCase):
    """Die Endpunkte arbeiten auf dem Standardordner - der wird umgebogen."""

    def setUp(self):
        self.folder = TemporaryDirectory()
        patcher = patch.object(ideas, "DEFAULT_DIR", Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def test_list_is_empty_at_first(self):
        payload = ideas.list_ideas_payload()
        self.assertEqual(payload["ideas"], [])
        self.assertEqual(payload["open"], 0)
        self.assertTrue(payload["file"].endswith("ideen.md"))

    def test_add_returns_entry_prompt_and_list(self):
        payload = ideas.add_idea_payload({"text": "Neue Idee", "context": CONTEXT})
        self.assertEqual(payload["idea"]["text"], "Neue Idee")
        self.assertIn("RSI-2 Dip Buy", payload["prompt"])
        self.assertEqual(payload["open"], 1)

    def test_status_and_delete(self):
        created = ideas.add_idea_payload({"text": "Idee"})["idea"]
        self.assertEqual(ideas.status_idea_payload({"id": created["id"], "status": "erledigt"})["open"], 0)
        self.assertEqual(ideas.delete_idea_payload({"id": created["id"]})["ideas"], [])

    def test_empty_text_through_the_endpoint_is_rejected(self):
        with self.assertRaises(IdeaError):
            ideas.add_idea_payload({"text": "  "})

    def test_payload_is_json_serialisable(self):
        ideas.add_idea_payload({"text": "Idee", "context": CONTEXT})
        json.dumps(ideas.list_ideas_payload(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
