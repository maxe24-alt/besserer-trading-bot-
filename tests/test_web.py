"""Tests der Dashboard-Oberflaeche, ohne Browser.

Der Anlass: ``<input type="number" value="100" min="1" step="5">`` ist nach
den HTML-Regeln ungueltig - 100 liegt nicht auf dem Raster 1, 6, 11, ... Der
Browser bricht das Absenden des Formulars daraufhin ab, und zwar lautlos:
keine Meldung, kein Fehler in der Konsole, der Knopf tut einfach nichts.
Diese Tests pruefen die Zahlenfelder gegen ihre eigenen Angaben und die
Verdrahtung zwischen HTML und JavaScript.
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
APP_JS = (WEB / "js" / "app.js").read_text(encoding="utf-8")
CHART_JS = (WEB / "js" / "chart.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "style.css").read_text(encoding="utf-8")


class _Collector(HTMLParser):
    """Sammelt alle Elemente mit ihren Attributen."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.elements.append((tag, {k: (v or "") for k, v in attrs}))

    handle_startendtag = handle_starttag


def _parse() -> list[tuple[str, dict[str, str]]]:
    collector = _Collector()
    collector.feed(HTML)
    return collector.elements


ELEMENTS = _parse()
IDS = {attrs["id"] for _, attrs in ELEMENTS if "id" in attrs}


class NumberInputTest(unittest.TestCase):
    def number_inputs(self):
        return [
            attrs for tag, attrs in ELEMENTS
            if tag == "input" and attrs.get("type") == "number"
        ]

    def test_there_are_number_inputs_to_check(self):
        self.assertGreaterEqual(len(self.number_inputs()), 4)

    def test_default_value_satisfies_min_max_and_step(self):
        """Sonst blockiert der Browser das Absenden, ohne etwas zu sagen."""
        for attrs in self.number_inputs():
            with self.subTest(field=attrs.get("id")):
                value = float(attrs["value"])
                minimum = attrs.get("min")
                maximum = attrs.get("max")
                step = attrs.get("step")

                if minimum is not None:
                    self.assertGreaterEqual(value, float(minimum))
                if maximum is not None:
                    self.assertLessEqual(value, float(maximum))

                if step and step != "any":
                    base = float(minimum) if minimum is not None else 0.0
                    steps = (value - base) / float(step)
                    # In Ganzzahlen rechnen, sonst schlaegt 0.1 + 0.2 zu.
                    self.assertAlmostEqual(
                        steps, round(steps), places=6,
                        msg=(f"{attrs.get('id')}: Wert {value} liegt nicht auf dem Raster "
                             f"(min={minimum}, step={step}). Der naechste gueltige Wert waere "
                             f"{base + round(steps) * float(step)}."),
                    )

    def test_every_field_sits_in_a_labelled_wrapper(self):
        for attrs in self.number_inputs():
            with self.subTest(field=attrs.get("id")):
                self.assertIn("id", attrs, "ohne id findet das JavaScript das Feld nicht")


class WiringTest(unittest.TestCase):
    """Jede id, die das JavaScript sucht, muss es im HTML auch geben."""

    def test_all_ids_used_by_the_script_exist(self):
        used = set(re.findall(r'\$\("([a-z0-9-]+)"\)', APP_JS))
        self.assertTrue(used, "keine id-Zugriffe gefunden")
        missing = sorted(used - IDS)
        self.assertEqual(missing, [], f"diese ids fehlen im HTML: {missing}")

    def test_the_form_and_its_submit_button_exist(self):
        self.assertIn("settings", IDS)
        button = next(
            (attrs for tag, attrs in ELEMENTS
             if tag == "button" and attrs.get("id") == "run-button"), None
        )
        self.assertIsNotNone(button, "der Knopf zum Starten fehlt")
        self.assertEqual(button.get("type"), "submit")

    def test_forms_are_not_nested(self):
        """Ein Formular im Formular waere ungueltiges HTML."""
        depth = 0
        for tag, _ in ELEMENTS:
            if tag == "form":
                depth += 1
        self.assertEqual(depth, 2, "erwartet: Einstellungen und Notizbuch")
        self.assertLess(HTML.index('id="settings"'), HTML.index("</form>"))

    def test_scripts_and_stylesheet_are_linked(self):
        for path in ("/css/style.css", "/js/chart.js", "/js/app.js"):
            with self.subTest(datei=path):
                self.assertIn(path, HTML)

    def test_invalid_fields_are_reported_to_the_user(self):
        """Der Auslöser dieses Testmoduls - lautloses Scheitern ist verboten."""
        self.assertIn('addEventListener("invalid"', APP_JS)


class StyleTest(unittest.TestCase):
    def test_every_css_class_used_by_the_script_is_defined(self):
        used = set(re.findall(r'class(?:Name)?\s*=\s*"([a-z][a-z0-9 -]*)"', APP_JS))
        used |= set(re.findall(r'classList\.(?:add|toggle)\("([a-z-]+)"', APP_JS))
        for name in {n for group in used for n in group.split()}:
            with self.subTest(klasse=name):
                self.assertIn(f".{name}", CSS, f"CSS-Klasse .{name} ist nirgends definiert")

    def test_series_colours_match_between_script_and_stylesheet(self):
        """Chart und Legende muessen dieselben Farben benutzen."""
        for colour in ("#199e70", "#c98500"):
            with self.subTest(farbe=colour):
                self.assertIn(colour, APP_JS)
                self.assertIn(colour, CSS)

    def test_charts_carry_no_horizontal_overflow_trap(self):
        self.assertIn("min-width: 0", CSS)


if __name__ == "__main__":
    unittest.main()
