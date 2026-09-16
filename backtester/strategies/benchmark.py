"""Die Vergleichsmassstaebe - vor allem Buy & Hold."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Param, PineSpec, Strategy, register


@register
class BuyAndHold(Strategy):
    key = "buy_hold"
    display_name = "Buy & Hold"
    category = "benchmark"
    description = (
        "Einmal kaufen, nie wieder anfassen. Der ehrlichste Massstab: jede "
        "Strategie muss erst einmal besser sein als Nichtstun."
    )
    params = ()

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="state",
            calc=("// Immer investiert - der Massstab fuer alles andere",),
            long_entry="true",
            long_exit="false",
        )

    @property
    def label(self) -> str:
        return "Buy & Hold"


@register
class RandomEntry(Strategy):
    key = "random"
    display_name = "Zufall"
    category = "benchmark"
    description = (
        "Wuerfelt die Position aus - mit festem Seed reproduzierbar. Nuetzlich, "
        "um zu pruefen, ob eine Strategie wirklich mehr kann als der Zufall."
    )
    params = (
        Param("long_probability", 0.5, "Long-Wahrscheinlichkeit", "float", 0.0, 1.0, 0.05),
        Param("seed", 42, "Zufalls-Seed", "int", 0, 10**6),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        rng = np.random.default_rng(self.settings["seed"])
        draws = rng.random(len(df))
        return pd.Series((draws < self.settings["long_probability"]).astype(float), index=df.index)

    @property
    def label(self) -> str:
        return "Zufall (Kontrollgruppe)"
