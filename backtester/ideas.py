"""Ideen-Postfach: Notizen aus dem Dashboard zu Strategien.

Der Zweck: waehrend man ein Ergebnis anschaut, faellt einem etwas ein -
"RSI-2 braucht einen Stop", "probier mal 5/30 statt 9/21". Genau dann soll
das festgehalten werden, samt dem Lauf, auf den es sich bezieht. Ohne diesen
Zusammenhang ist eine Notiz drei Tage spaeter wertlos.

Gespeichert wird zweimal:
    ideen/ideen.json   maschinenlesbar, Quelle der Wahrheit
    ideen/ideen.md     lesbar und git-tauglich, wird bei jeder Aenderung neu
                       geschrieben - das ist die Datei, die man weitergibt

Das Dashboard laeuft lokal ohne Netz und ohne API-Schluessel; hier wird
deshalb nur geschrieben und gelesen, nichts verschickt.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(os.environ.get("BACKTESTER_IDEAS_DIR", "ideen"))

JSON_NAME = "ideen.json"
MARKDOWN_NAME = "ideen.md"

MAX_TEXT_LENGTH = 4000
STATUSES = ("offen", "erledigt")


class IdeaError(ValueError):
    """Die Notiz konnte nicht gespeichert werden."""


# --- Speicher ------------------------------------------------------------
def _json_path(directory: Path | str | None = None) -> Path:
    return Path(directory or DEFAULT_DIR) / JSON_NAME


def load(directory: Path | str | None = None) -> list[dict[str, Any]]:
    """Liest alle Notizen, neueste zuerst."""
    path = _json_path(directory)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict) and entry.get("id")]


def _save(entries: list[dict[str, Any]], directory: Path | str | None = None) -> None:
    base = Path(directory or DEFAULT_DIR)
    base.mkdir(parents=True, exist_ok=True)
    (base / JSON_NAME).write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (base / MARKDOWN_NAME).write_text(to_markdown(entries), encoding="utf-8")


# --- Schreiben -----------------------------------------------------------
def add(
    text: str,
    context: dict[str, Any] | None = None,
    directory: Path | str | None = None,
) -> dict[str, Any]:
    """Legt eine Notiz an und gibt sie zurueck.

    Args:
        text: Was einem eingefallen ist.
        context: Der Lauf, auf den es sich bezieht (Markt, Strategie, Kennzahlen).
        directory: Zielordner, sonst ``ideen/``.

    Raises:
        IdeaError: Bei leerem oder zu langem Text.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise IdeaError("Die Notiz ist leer.")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise IdeaError(f"Die Notiz ist laenger als {MAX_TEXT_LENGTH} Zeichen.")

    entry = {
        # Die ID kommt vom Server, nie vom Browser.
        "id": uuid.uuid4().hex[:12],
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "offen",
        "text": cleaned,
        "context": _clean_context(context),
    }

    entries = load(directory)
    entries.insert(0, entry)
    _save(entries, directory)
    return entry


def set_status(idea_id: str, status: str, directory: Path | str | None = None) -> dict[str, Any]:
    """Setzt eine Notiz auf offen oder erledigt."""
    if status not in STATUSES:
        raise IdeaError(f"Status muss {' oder '.join(STATUSES)} sein, nicht {status!r}.")

    entries = load(directory)
    for entry in entries:
        if entry["id"] == idea_id:
            entry["status"] = status
            _save(entries, directory)
            return entry
    raise IdeaError(f"Keine Notiz mit der ID {idea_id!r}.")


def remove(idea_id: str, directory: Path | str | None = None) -> None:
    """Loescht eine Notiz."""
    entries = load(directory)
    remaining = [entry for entry in entries if entry["id"] != idea_id]
    if len(remaining) == len(entries):
        raise IdeaError(f"Keine Notiz mit der ID {idea_id!r}.")
    _save(remaining, directory)


def _clean_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Uebernimmt nur bekannte Felder - der Browser darf hier nichts einschleusen."""
    if not isinstance(context, dict):
        return {}

    allowed_top = {
        "symbol", "interval", "start", "end", "strategy", "strategy_label", "provider",
    }
    allowed_metrics = {
        "net_pnl", "return_pct", "max_drawdown_pct", "trades", "win_rate_pct",
        "profit_factor", "sharpe",
    }
    allowed_settings = {"capital", "fee", "slippage", "exposure", "allow_short"}

    out: dict[str, Any] = {}
    for key in allowed_top:
        value = context.get(key)
        if isinstance(value, str) and value:
            out[key] = value[:120]

    for name, allowed in (("metrics", allowed_metrics), ("settings", allowed_settings)):
        source = context.get(name)
        if isinstance(source, dict):
            picked = {
                k: v for k, v in source.items()
                if k in allowed and isinstance(v, (int, float, bool))
            }
            if picked:
                out[name] = picked

    params = context.get("params")
    if isinstance(params, dict):
        picked = {
            str(k)[:40]: v for k, v in list(params.items())[:20]
            if isinstance(v, (int, float, bool, str))
        }
        if picked:
            out["params"] = picked

    return out


# --- Darstellung ---------------------------------------------------------
def to_markdown(entries: list[dict[str, Any]]) -> str:
    """Baut die lesbare Fassung - das ist die Datei, die man weitergibt."""
    lines = [
        "# Strategie-Ideen",
        "",
        "Notizen aus dem Dashboard. Jede haengt an dem Lauf, bei dem sie",
        "entstanden ist - Markt, Zeitraum, Strategie und deren Kennzahlen.",
        "",
    ]
    if not entries:
        lines.append("_Noch nichts notiert._")
        return "\n".join(lines) + "\n"

    open_count = sum(1 for e in entries if e.get("status") != "erledigt")
    lines.append(f"**{open_count} offen**, {len(entries) - open_count} erledigt.")
    lines.append("")

    for entry in entries:
        mark = "x" if entry.get("status") == "erledigt" else " "
        date = str(entry.get("created", ""))[:10]
        lines.append(f"## [{mark}] {date} · `{entry['id']}`")
        lines.append("")
        lines.append(entry.get("text", "").strip())
        lines.append("")
        block = context_lines(entry.get("context") or {})
        if block:
            lines.extend(block)
            lines.append("")

    return "\n".join(lines) + "\n"


def context_lines(context: dict[str, Any]) -> list[str]:
    """Der Lauf hinter einer Notiz, als Aufzaehlung."""
    if not context:
        return []

    out = ["> **Bezieht sich auf**  "]
    market = " · ".join(
        part for part in (
            context.get("symbol"),
            context.get("interval"),
            f"{context.get('start', '')} bis {context.get('end', '')}".strip(" bis"),
        ) if part
    )
    if market:
        out.append(f"> Markt: {market}  ")
    if context.get("strategy_label"):
        params = context.get("params") or {}
        suffix = f" ({', '.join(f'{k}={v}' for k, v in params.items())})" if params else ""
        out.append(f"> Strategie: {context['strategy_label']}{suffix}  ")

    metrics = context.get("metrics") or {}
    if metrics:
        parts = []
        if "net_pnl" in metrics:
            parts.append(f"Netto {metrics['net_pnl']:+,.0f} $".replace(",", "."))
        if "return_pct" in metrics:
            parts.append(f"{metrics['return_pct']:+.1f} %")
        if "max_drawdown_pct" in metrics:
            parts.append(f"Max DD {metrics['max_drawdown_pct']:.1f} %")
        if "trades" in metrics:
            parts.append(f"{metrics['trades']} Trades")
        if metrics.get("profit_factor"):
            parts.append(f"PF {metrics['profit_factor']:.2f}")
        out.append(f"> Ergebnis: {' · '.join(parts)}  ")

    settings = context.get("settings") or {}
    if settings:
        out.append(
            "> Bedingungen: "
            f"{settings.get('capital', 0):,.0f} $ Start · ".replace(",", ".")
            + f"{settings.get('fee', 0)} % je Seite · {settings.get('slippage', 0)} Tick"
        )

    return out


def to_prompt(entry: dict[str, Any]) -> str:
    """Formt eine Notiz zu einem Text, den man direkt an Claude weitergibt."""
    lines = [entry.get("text", "").strip(), ""]
    block = context_lines(entry.get("context") or {})
    if block:
        lines.extend(line.lstrip("> ").rstrip() for line in block)
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


# --- Endpunkte des Dashboards -------------------------------------------
def list_ideas_payload(_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET /api/ideas"""
    entries = load()
    return {
        "ideas": entries,
        "open": sum(1 for e in entries if e.get("status") != "erledigt"),
        "file": str((Path(DEFAULT_DIR) / MARKDOWN_NAME).resolve()),
    }


def add_idea_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /api/ideas"""
    entry = add(payload.get("text", ""), payload.get("context"))
    return {"idea": entry, "prompt": to_prompt(entry), **list_ideas_payload()}


def status_idea_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /api/ideas/status"""
    set_status(str(payload.get("id", "")), str(payload.get("status", "")))
    return list_ideas_payload()


def delete_idea_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /api/ideas/delete"""
    remove(str(payload.get("id", "")))
    return list_ideas_payload()
