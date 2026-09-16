"""Basisklasse und Registry fuer Strategien.

Eine Strategie liefert fuer jede Bar eine Zielposition in {-1, 0, +1}:

    +1  long
     0  flat
    -1  short

Die Entscheidung faellt am Schluss der Bar; die Engine setzt sie erst zur
Eroeffnung der naechsten Bar um. Damit kann keine Strategie in die Zukunft
schauen, egal wie sie intern rechnet.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Param:
    """Ein einstellbarer Parameter - auch die Basis fuer die Dashboard-Regler."""

    name: str
    default: Any
    label: str
    kind: str = "int"  # "int" | "float" | "bool"
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0

    def coerce(self, value: Any) -> Any:
        """Wandelt einen Eingabewert in den richtigen Typ und kappt ihn."""
        if value is None or value == "":
            return self.default
        if self.kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on", "ja"}
            return bool(value)
        number = float(value)
        if self.minimum is not None:
            number = max(number, self.minimum)
        if self.maximum is not None:
            number = min(number, self.maximum)
        return int(round(number)) if self.kind == "int" else number


@dataclass(frozen=True)
class PineSpec:
    """Die Pine-Script-Fassung einer Strategie.

    Aus diesen Bausteinen setzt ``backtester.pine`` ein lauffaehiges
    TradingView-Skript zusammen. Die Bedingungen muessen exakt der
    Python-Logik entsprechen - sonst weichen die Ergebnisse ab.

    ``mode`` unterscheidet die beiden Bauarten:
        "state" - die Position gilt, solange ``long_entry`` wahr ist
                  (``long_exit`` ist dann die Gegenbedingung).
        "event" - ``long_entry`` oeffnet, ``long_exit`` schliesst.
    """

    inputs: tuple[str, ...] = ()
    calc: tuple[str, ...] = ()
    long_entry: str = "false"
    long_exit: str = "false"
    plots: tuple[str, ...] = ()
    mode: str = "event"
    overlay: bool = True  # False = eigenes Chartfenster (Oszillatoren)


class Strategy(abc.ABC):
    """Gemeinsame Basis aller Strategien."""

    key: str = "base"
    display_name: str = "Base"
    category: str = "sonstige"
    description: str = ""
    params: tuple[Param, ...] = ()

    def __init__(self, **overrides: Any) -> None:
        self.settings: dict[str, Any] = {}
        known = {p.name: p for p in self.params}
        for name, spec in known.items():
            self.settings[name] = spec.coerce(overrides.get(name, spec.default))

        unknown = set(overrides) - set(known)
        if unknown:
            raise ValueError(
                f"{self.key}: unbekannte Parameter {sorted(unknown)}. "
                f"Erlaubt: {sorted(known) or '(keine)'}"
            )

    # -- von Subklassen zu implementieren ---------------------------------
    @abc.abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Liefert die Zielposition je Bar als Serie in {-1, 0, +1}."""

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Optionale Linien fuer den Chart im Dashboard."""
        return {}

    def pine(self) -> PineSpec | None:
        """Die Pine-Script-Fassung, oder ``None``, wenn es keine gibt."""
        return None

    # -- oeffentliche API --------------------------------------------------
    def signals(self, df: pd.DataFrame) -> pd.Series:
        """Bereinigte Zielposition: nur -1/0/+1, keine NaN."""
        raw = self.compute(df)
        target = pd.Series(raw, index=df.index).astype(float)
        target = target.fillna(0.0).clip(-1.0, 1.0)
        return target.round().astype(int)

    @property
    def label(self) -> str:
        """Anzeigename inklusive der aktiven Parameter, z. B. "EMA Cross (9/21)"."""
        return self.display_name

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.display_name,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "params": self.settings,
            "has_pine": self.pine() is not None,
        }

    def __repr__(self) -> str:  # pragma: no cover - reine Diagnose
        args = ", ".join(f"{k}={v}" for k, v in self.settings.items())
        return f"{type(self).__name__}({args})"


def hold_position(entries: pd.Series, exits: pd.Series, direction: int = 1) -> pd.Series:
    """Baut aus Ein- und Ausstiegssignalen eine gehaltene Position.

    Der Zustand bleibt nach einem Einstieg bestehen, bis ein Ausstieg kommt -
    das ist der Unterschied zwischen "Signal" und "Position".
    """
    enter = entries.fillna(False).to_numpy(dtype=bool)
    exit_ = exits.fillna(False).to_numpy(dtype=bool)

    position = np.zeros(len(enter), dtype=float)
    active = False
    for i in range(len(enter)):
        if active and exit_[i]:
            active = False
        elif not active and enter[i]:
            active = True
        position[i] = direction if active else 0.0

    return pd.Series(position, index=entries.index)


def state_position(long_on: pd.Series, short_on: pd.Series | None = None) -> pd.Series:
    """Zustandsbasierte Position: solange die Bedingung gilt, ist sie aktiv."""
    position = long_on.fillna(False).astype(float)
    if short_on is not None:
        position = position - short_on.fillna(False).astype(float)
    return position


# --- Registry ------------------------------------------------------------
_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """Dekorator, der eine Strategie in die Registry aufnimmt."""
    if cls.key in _REGISTRY:
        raise ValueError(f"Strategie-Key {cls.key!r} ist schon vergeben")
    _REGISTRY[cls.key] = cls
    return cls


def available() -> dict[str, type[Strategy]]:
    return dict(_REGISTRY)


def get(key: str, **params: Any) -> Strategy:
    """Erzeugt eine Strategie-Instanz aus ihrem Key."""
    normalized = (key or "").strip().lower().replace("-", "_")
    if normalized not in _REGISTRY:
        raise KeyError(
            f"Unbekannte Strategie {key!r}. Verfuegbar: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[normalized](**params)
