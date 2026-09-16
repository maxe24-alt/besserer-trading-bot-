"""Mean-Reversion-Strategien - sie kaufen Schwaeche statt Staerke."""

from __future__ import annotations

import pandas as pd

from .. import indicators as ta
from .base import Param, PineSpec, Strategy, hold_position, register


@register
class RsiMeanReversion(Strategy):
    key = "rsi_mean_reversion"
    display_name = "RSI Mean Reversion"
    category = "mean-reversion"
    description = (
        "Kauft, wenn der RSI unter die ueberverkaufte Schwelle faellt, und "
        "verkauft bei Rueckkehr zur Mitte. Viele kleine Gewinne, seltene grosse Verluste."
    )
    params = (
        Param("length", 14, "RSI-Laenge", "int", 2, 100),
        Param("oversold", 30, "Ueberverkauft", "int", 1, 49),
        Param("exit_level", 55, "Ausstieg RSI", "int", 20, 99),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        rsi = ta.rsi(df["close"], self.settings["length"])
        return hold_position(rsi < self.settings["oversold"], rsi > self.settings["exit_level"])

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {f"RSI {self.settings['length']}": ta.rsi(df["close"], self.settings["length"])}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            overlay=False,
            inputs=(
                'rsiLen = input.int({length}, "RSI-Laenge", minval=2, group="Strategie")',
                'oversold = input.int({oversold}, "Ueberverkauft", minval=1, maxval=49, group="Strategie")',
                'exitLevel = input.int({exit_level}, "Ausstieg RSI", minval=20, maxval=99, group="Strategie")',
            ),
            calc=("rsiValue = ta.rsi(close, rsiLen)",),
            long_entry="rsiValue < oversold",
            long_exit="rsiValue > exitLevel",
            plots=(
                'plot(rsiValue, "RSI", color=color.new(#7aa2f7, 0), linewidth=2)',
                'hline(oversold, "Ueberverkauft", color=color.new(#5ce1a6, 40))',
                'hline(exitLevel, "Ausstieg", color=color.new(#ff5c5c, 40))',
            ),
        )

    @property
    def label(self) -> str:
        return f"RSI Mean Reversion ({self.settings['length']})"


@register
class Rsi2Dip(Strategy):
    key = "rsi2_dip"
    display_name = "RSI-2 Dip Buy (Connors)"
    category = "mean-reversion"
    description = (
        "Larry Connors' Klassiker: Rueckschlaege im Aufwaertstrend kaufen. "
        "Nur long ueber der 200er SMA, Einstieg bei RSI(2) unter 10, Ausstieg ueber der 5er SMA."
    )
    params = (
        Param("rsi_length", 2, "RSI-Laenge", "int", 2, 30),
        Param("entry_level", 10, "Einstieg RSI", "int", 1, 49),
        Param("trend_length", 200, "Trendfilter SMA", "int", 20, 500),
        Param("exit_sma", 5, "Ausstieg SMA", "int", 2, 50),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        s = self.settings
        rsi = ta.rsi(df["close"], s["rsi_length"])
        trend = ta.sma(df["close"], s["trend_length"])
        exit_sma = ta.sma(df["close"], s["exit_sma"])

        entry = (df["close"] > trend) & (rsi < s["entry_level"])
        exit_ = (df["close"] > exit_sma) | (df["close"] < trend)
        return hold_position(entry, exit_)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        s = self.settings
        return {
            f"SMA {s['trend_length']}": ta.sma(df["close"], s["trend_length"]),
            f"SMA {s['exit_sma']}": ta.sma(df["close"], s["exit_sma"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'rsiLen = input.int({rsi_length}, "RSI-Laenge", minval=2, group="Strategie")',
                'entryLevel = input.int({entry_level}, "Einstieg RSI", minval=1, maxval=49, group="Strategie")',
                'trendLen = input.int({trend_length}, "Trendfilter SMA", minval=20, group="Strategie")',
                'exitSmaLen = input.int({exit_sma}, "Ausstieg SMA", minval=2, group="Strategie")',
            ),
            calc=(
                "rsiValue = ta.rsi(close, rsiLen)",
                "trendSma = ta.sma(close, trendLen)",
                "exitSma = ta.sma(close, exitSmaLen)",
            ),
            long_entry="close > trendSma and rsiValue < entryLevel",
            long_exit="close > exitSma or close < trendSma",
            plots=(
                'plot(trendSma, "Trend-SMA", color=color.new(#f0b232, 0), linewidth=2)',
                'plot(exitSma, "Ausstiegs-SMA", color=color.new(#5ce1a6, 0))',
            ),
        )

    @property
    def label(self) -> str:
        return f"RSI-2 Dip Buy (Connors)"


@register
class BollingerReversion(Strategy):
    key = "bollinger_reversion"
    display_name = "Bollinger Reversion"
    category = "mean-reversion"
    description = (
        "Kauft den Ruecksetzer auf das untere Bollinger-Band und steigt an der "
        "Mittellinie wieder aus. Lebt von der Rueckkehr zum Mittelwert."
    )
    params = (
        Param("length", 20, "Fenster", "int", 5, 200),
        Param("num_std", 2.0, "Standardabweichungen", "float", 0.5, 5.0, 0.1),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        lower, mid, _ = ta.bollinger(df["close"], self.settings["length"], self.settings["num_std"])
        return hold_position(df["close"] < lower, df["close"] > mid)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        lower, mid, upper = ta.bollinger(df["close"], self.settings["length"], self.settings["num_std"])
        return {"BB unten": lower, "BB Mitte": mid, "BB oben": upper}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'bbLen = input.int({length}, "Fenster", minval=5, group="Strategie")',
                'bbStd = input.float({num_std}, "Standardabweichungen", minval=0.5, step=0.1, group="Strategie")',
            ),
            calc=("[bbMid, bbUpper, bbLower] = ta.bb(close, bbLen, bbStd)",),
            long_entry="close < bbLower",
            long_exit="close > bbMid",
            plots=(
                'pU = plot(bbUpper, "BB oben", color=color.new(#ff5c5c, 30))',
                'pL = plot(bbLower, "BB unten", color=color.new(#5ce1a6, 30))',
                'plot(bbMid, "BB Mitte", color=color.new(#f0b232, 0))',
                'fill(pU, pL, color=color.new(#7aa2f7, 92))',
            ),
        )

    @property
    def label(self) -> str:
        s = self.settings
        return f"Bollinger Reversion ({s['length']},{s['num_std']:g})"


@register
class VwapReversion(Strategy):
    key = "vwap_reversion"
    display_name = "VWAP Reversion"
    category = "mean-reversion"
    description = (
        "Kauft, wenn der Kurs deutlich unter den rollierenden VWAP faellt, und "
        "verkauft bei Rueckkehr darueber. Orientiert sich am volumengewichteten Mittel."
    )
    params = (
        Param("length", 20, "VWAP-Fenster", "int", 5, 200),
        Param("threshold", 1.0, "Abstand in Prozent", "float", 0.0, 20.0, 0.1),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        vwap = ta.rolling_vwap(df, self.settings["length"])
        band = vwap * (1.0 - self.settings["threshold"] / 100.0)
        return hold_position(df["close"] < band, df["close"] > vwap)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {f"VWAP {self.settings['length']}": ta.rolling_vwap(df, self.settings["length"])}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'vwapLen = input.int({length}, "VWAP-Fenster", minval=5, group="Strategie")',
                'thresholdPct = input.float({threshold}, "Abstand in Prozent", minval=0.0, step=0.1, group="Strategie")',
            ),
            calc=(
                "// Rollierender VWAP; ohne Volumen faellt er auf den Typical Price zurueck",
                "typicalPrice = hlc3",
                "volumeSum = math.sum(volume, vwapLen)",
                "vwapValue = volumeSum > 0 ? math.sum(typicalPrice * volume, vwapLen) / volumeSum : ta.sma(typicalPrice, vwapLen)",
                "lowerBand = vwapValue * (1 - thresholdPct / 100)",
            ),
            long_entry="close < lowerBand",
            long_exit="close > vwapValue",
            plots=(
                'plot(vwapValue, "VWAP", color=color.new(#f0b232, 0), linewidth=2)',
                'plot(lowerBand, "Kaufschwelle", color=color.new(#5ce1a6, 0))',
            ),
        )

    @property
    def label(self) -> str:
        return f"VWAP Reversion ({self.settings['length']}d)"


@register
class StochasticTrend(Strategy):
    key = "stochastic_trend"
    display_name = "Stochastik + Trendfilter"
    category = "mean-reversion"
    description = (
        "Kauft ueberverkaufte Stochastik, aber nur oberhalb der Trend-SMA. "
        "Der Filter sortiert genau die Rueckschlaege aus, die keine sind."
    )
    params = (
        Param("k_length", 14, "%K-Laenge", "int", 2, 100),
        Param("k_smooth", 3, "%K-Glaettung", "int", 1, 20),
        Param("d_smooth", 3, "%D-Glaettung", "int", 1, 20),
        Param("oversold", 20, "Ueberverkauft", "int", 1, 49),
        Param("exit_level", 80, "Ausstieg", "int", 30, 99),
        Param("trend_length", 200, "Trendfilter SMA", "int", 20, 500),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        s = self.settings
        percent_k, percent_d = ta.stochastic(df, s["k_length"], s["k_smooth"], s["d_smooth"])
        trend = ta.sma(df["close"], s["trend_length"])

        entry = (df["close"] > trend) & ta.crossover(percent_k, percent_d) & (percent_k < s["oversold"])
        exit_ = (percent_k > s["exit_level"]) | (df["close"] < trend)
        return hold_position(entry, exit_)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        s = self.settings
        percent_k, percent_d = ta.stochastic(df, s["k_length"], s["k_smooth"], s["d_smooth"])
        return {
            "%K": percent_k,
            "%D": percent_d,
            f"SMA {s['trend_length']}": ta.sma(df["close"], s["trend_length"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            overlay=False,
            inputs=(
                'kLen = input.int({k_length}, "%K-Laenge", minval=2, group="Strategie")',
                'kSmooth = input.int({k_smooth}, "%K-Glaettung", minval=1, group="Strategie")',
                'dSmooth = input.int({d_smooth}, "%D-Glaettung", minval=1, group="Strategie")',
                'oversold = input.int({oversold}, "Ueberverkauft", minval=1, maxval=49, group="Strategie")',
                'exitLevel = input.int({exit_level}, "Ausstieg", minval=30, maxval=99, group="Strategie")',
                'trendLen = input.int({trend_length}, "Trendfilter SMA", minval=20, group="Strategie")',
            ),
            calc=(
                "percentK = ta.sma(ta.stoch(close, high, low, kLen), kSmooth)",
                "percentD = ta.sma(percentK, dSmooth)",
                "trendSma = ta.sma(close, trendLen)",
            ),
            long_entry="close > trendSma and ta.crossover(percentK, percentD) and percentK < oversold",
            long_exit="percentK > exitLevel or close < trendSma",
            plots=(
                'plot(percentK, "%K", color=color.new(#5ce1a6, 0), linewidth=2)',
                'plot(percentD, "%D", color=color.new(#f0b232, 0))',
                'hline(oversold, "Ueberverkauft", color=color.new(#5ce1a6, 40))',
                'hline(exitLevel, "Ausstieg", color=color.new(#ff5c5c, 40))',
            ),
        )

    @property
    def label(self) -> str:
        return "Stochastik + Trendfilter"
