"""Strategie-Registry.

Neue Strategien brauchen nur eine Unterklasse von ``Strategy`` mit dem
Dekorator ``@register`` - Registry, CLI und Dashboard finden sie dann
automatisch.
"""

from __future__ import annotations

from .base import Param, Strategy, available, get, hold_position, register, state_position

# Die Importe registrieren die eingebauten Strategien.
from . import benchmark, mean_reversion, trend  # noqa: F401  (Seiteneffekt)

# Reihenfolge fuer Listen und die Gauntlet-Laeufe.
DEFAULT_ORDER: tuple[str, ...] = (
    "ema_cross",
    "ichimoku",
    "high_52w",
    "turtle_breakout",
    "macd_cross",
    "stochastic_trend",
    "golden_cross",
    "vwap_reversion",
    "rsi2_dip",
    "bollinger_reversion",
    "rsi_mean_reversion",
    "supertrend",
)

BENCHMARK_KEY = "buy_hold"


def all_keys(include_benchmarks: bool = False) -> list[str]:
    """Alle Strategie-Keys, die bekannten zuerst in fester Reihenfolge."""
    registry = available()
    ordered = [k for k in DEFAULT_ORDER if k in registry]
    rest = sorted(
        k
        for k, cls in registry.items()
        if k not in ordered and (include_benchmarks or cls.category != "benchmark")
    )
    return ordered + rest


def catalog(include_benchmarks: bool = True) -> list[dict]:
    """Metadaten aller Strategien - genau das, was das Dashboard braucht."""
    registry = available()
    keys = all_keys(include_benchmarks=include_benchmarks)
    entries = []
    for key in keys:
        cls = registry[key]
        instance = cls()
        entries.append(
            {
                "key": key,
                "name": cls.display_name,
                "label": instance.label,
                "category": cls.category,
                "description": cls.description,
                "has_pine": instance.pine() is not None,
                "params": [
                    {
                        "name": p.name,
                        "label": p.label,
                        "default": p.default,
                        "kind": p.kind,
                        "min": p.minimum,
                        "max": p.maximum,
                        "step": p.step,
                    }
                    for p in cls.params
                ],
            }
        )
    return entries


__all__ = [
    "BENCHMARK_KEY",
    "DEFAULT_ORDER",
    "Param",
    "Strategy",
    "all_keys",
    "available",
    "catalog",
    "get",
    "hold_position",
    "register",
    "state_position",
]
