"""Webserver fuer das Dashboard.

Bewusst nur mit der Standardbibliothek gebaut - kein Flask, kein FastAPI.
Das ganze Projekt kommt damit mit pandas, numpy und requests aus.

Endpunkte:
    GET  /                 Dashboard
    GET  /api/catalog      Strategien, Datenquellen, Kontrakte
    GET  /api/ideas        Gespeicherte Strategie-Notizen
    POST /api/backtest     Lauf starten, Ergebnis als JSON
    POST /api/pine         Pine-Quelltext einer Strategie
    POST /api/ideas        Notiz anlegen
    POST /api/ideas/status Notiz auf offen/erledigt setzen
    POST /api/ideas/delete Notiz loeschen
"""

from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .data import DataError, load_bars, provider_infos
from .engine import BacktestConfig, run_gauntlet
from .engine.results import json_default
from .ideas import IdeaError, add_idea_payload, delete_idea_payload, list_ideas_payload, status_idea_payload
from .instruments import known_instruments
from .pine import to_pine, tradingview_symbol
from .strategies import all_keys, catalog

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

MAX_BODY_BYTES = 1 << 20  # 1 MB reicht fuer jede Anfrage dieses Dashboards


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "backtester/1.0"

    # -- Hilfen ----------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, default=json_default, allow_nan=False).encode("utf-8")
        self._send(status, body, MIME_TYPES[".json"])

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("Anfrage ist zu gross")
        return json.loads(self.rfile.read(length) or b"{}")

    def log_message(self, fmt: str, *args) -> None:  # leiser als die Vorgabe
        return

    # -- Routen ----------------------------------------------------------
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/catalog":
            self._send_json(build_catalog())
            return
        if path == "/api/ideas":
            self._send_json(list_ideas_payload())
            return
        self._serve_static(path)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        routes = {
            "/api/backtest": handle_backtest,
            "/api/pine": handle_pine,
            "/api/ideas": add_idea_payload,
            "/api/ideas/status": status_idea_payload,
            "/api/ideas/delete": delete_idea_payload,
        }
        handler = routes.get(path)
        if handler is None:
            self._send_json({"error": f"Unbekannter Endpunkt {path}"}, 404)
            return
        try:
            self._send_json(handler(self._read_json()))
        except DataError as exc:
            self._send_json({"error": f"Daten konnten nicht geladen werden: {exc}"}, 400)
        except IdeaError as exc:
            self._send_json({"error": str(exc)}, 400)
        except (KeyError, ValueError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # pragma: no cover - letzte Auffanglinie
            traceback.print_exc()
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _serve_static(self, path: str) -> None:
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return

        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()

        # Kein Ausbrechen aus dem web/-Ordner.
        if not target.is_file() or WEB_ROOT.resolve() not in target.parents:
            self._send(404, b"Nicht gefunden", "text/plain; charset=utf-8")
            return

        content_type = MIME_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), content_type)


# --- Endpunkt-Logik ------------------------------------------------------
def build_catalog() -> dict:
    """Alles, was das Dashboard beim Start braucht."""
    return {
        "strategies": catalog(include_benchmarks=False),
        "providers": [
            {
                "key": info.key,
                "name": info.name,
                "needs_key": info.needs_key,
                "key_env": info.key_env,
                "asset_classes": info.asset_classes,
                "note": info.note,
                "signup_url": info.signup_url,
            }
            for info in provider_infos()
        ],
        "instruments": [
            {
                "symbol": inst.symbol,
                "name": inst.name,
                "kind": inst.kind,
                "point_value": inst.point_value,
                "tradingview": tradingview_symbol(inst.symbol),
            }
            for inst in known_instruments()
        ],
        "intervals": ["1d", "1h", "30m", "15m", "5m", "1m"],
    }


def _config_from_payload(payload: dict) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=float(payload.get("capital", 100_000)),
        fee_pct=float(payload.get("fee", 0.1)),
        slippage_ticks=float(payload.get("slippage", 1.0)),
        exposure=float(payload.get("exposure", 1.0)),
        long_only=not bool(payload.get("allow_short", False)),
        compounding=bool(payload.get("compounding", True)),
    )


def handle_backtest(payload: dict) -> dict:
    """Fuehrt einen Gauntlet-Lauf aus und liefert das Ergebnis als JSON."""
    symbol = payload.get("symbol") or "ES=F"
    interval = payload.get("interval") or "1d"
    # Fehlt der Schluessel, laufen alle Strategien. Steht er aber da und ist
    # leer, war das eine Auswahl - dann wird das gemeldet statt still alles
    # zu rechnen.
    keys = all_keys() if "strategies" not in payload else payload["strategies"]
    if not isinstance(keys, list) or not keys:
        raise ValueError("Bitte mindestens eine Strategie auswaehlen")

    unknown = [k for k in keys if k not in all_keys(include_benchmarks=True)]
    if unknown:
        raise ValueError(f"Unbekannte Strategien: {', '.join(unknown)}")

    result = run_gauntlet(
        symbol=symbol,
        strategies=keys,
        start=payload.get("start") or "2015-01-01",
        end=payload.get("end") or None,
        interval=interval,
        provider=payload.get("provider") or "yahoo",
        config=_config_from_payload(payload),
        params=payload.get("params") or None,
    )
    data = result.to_dict(include_series=True, max_points=1200)
    data["tradingview"] = tradingview_symbol(symbol)
    return data


def handle_pine(payload: dict) -> dict:
    """Liefert den Pine-Quelltext einer Strategie."""
    key = payload.get("strategy")
    if not key:
        raise ValueError("Es wurde keine Strategie angegeben")

    symbol = payload.get("symbol") or "ES=F"
    source = to_pine(
        key,
        symbol=symbol,
        start=payload.get("start") or "2015-01-01",
        end=payload.get("end") or None,
        interval=payload.get("interval") or "1d",
        config=_config_from_payload(payload),
        **(payload.get("params") or {}),
    )
    return {"strategy": key, "symbol": symbol, "tradingview": tradingview_symbol(symbol), "source": source}


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Startet den Server, bis Strg+C kommt."""
    if not WEB_ROOT.is_dir():
        raise RuntimeError(f"Der Ordner {WEB_ROOT} fehlt - ohne ihn gibt es kein Dashboard.")
    httpd = ThreadingHTTPServer((host, port), DashboardHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
