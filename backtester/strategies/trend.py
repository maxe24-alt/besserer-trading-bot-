"""Trendfolge-Strategien."""

from __future__ import annotations

import pandas as pd

from .. import indicators as ta
from .base import Param, PineSpec, Strategy, hold_position, register, state_position


@register
class EmaCross(Strategy):
    key = "ema_cross"
    display_name = "EMA Cross"
    category = "trend"
    description = (
        "Long, solange die schnelle EMA ueber der langsamen liegt. Der Klassiker "
        "unter den Trendfiltern: wenige, dafuer lange Trades."
    )
    params = (
        Param("fast", 9, "Schnelle EMA", "int", 2, 200),
        Param("slow", 21, "Langsame EMA", "int", 3, 400),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        fast = ta.ema(df["close"], self.settings["fast"])
        slow = ta.ema(df["close"], self.settings["slow"])
        return state_position(fast > slow, slow > fast)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {
            f"EMA {self.settings['fast']}": ta.ema(df["close"], self.settings["fast"]),
            f"EMA {self.settings['slow']}": ta.ema(df["close"], self.settings["slow"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="state",
            inputs=(
                'fastLen = input.int({fast}, "Schnelle EMA", minval=2, group="Strategie")',
                'slowLen = input.int({slow}, "Langsame EMA", minval=3, group="Strategie")',
            ),
            calc=(
                "fastEma = ta.ema(close, fastLen)",
                "slowEma = ta.ema(close, slowLen)",
            ),
            long_entry="fastEma > slowEma",
            long_exit="slowEma > fastEma",
            plots=(
                'plot(fastEma, "EMA schnell", color=color.new(#5ce1a6, 0), linewidth=2)',
                'plot(slowEma, "EMA langsam", color=color.new(#f0b232, 0), linewidth=2)',
            ),
        )

    @property
    def label(self) -> str:
        return f"EMA Cross ({self.settings['fast']}/{self.settings['slow']})"


@register
class GoldenCross(Strategy):
    key = "golden_cross"
    display_name = "Golden Cross"
    category = "trend"
    description = (
        "Long, wenn die 50er SMA ueber der 200er liegt. Extrem traege - sie "
        "verpasst den Einstieg, haelt dafuer die grossen Bewegungen komplett."
    )
    params = (
        Param("fast", 50, "Schnelle SMA", "int", 5, 200),
        Param("slow", 200, "Langsame SMA", "int", 20, 500),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        fast = ta.sma(df["close"], self.settings["fast"])
        slow = ta.sma(df["close"], self.settings["slow"])
        return state_position(fast > slow, slow > fast)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {
            f"SMA {self.settings['fast']}": ta.sma(df["close"], self.settings["fast"]),
            f"SMA {self.settings['slow']}": ta.sma(df["close"], self.settings["slow"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="state",
            inputs=(
                'fastLen = input.int({fast}, "Schnelle SMA", minval=5, group="Strategie")',
                'slowLen = input.int({slow}, "Langsame SMA", minval=20, group="Strategie")',
            ),
            calc=(
                "fastSma = ta.sma(close, fastLen)",
                "slowSma = ta.sma(close, slowLen)",
            ),
            long_entry="fastSma > slowSma",
            long_exit="slowSma > fastSma",
            plots=(
                'plot(fastSma, "SMA schnell", color=color.new(#5ce1a6, 0), linewidth=2)',
                'plot(slowSma, "SMA langsam", color=color.new(#f0b232, 0), linewidth=2)',
            ),
        )

    @property
    def label(self) -> str:
        return f"Golden Cross ({self.settings['fast']}/{self.settings['slow']})"


@register
class MacdCross(Strategy):
    key = "macd_cross"
    display_name = "MACD Crossover"
    category = "trend"
    description = (
        "Long, wenn die MACD-Linie ueber ihrer Signallinie notiert. Reagiert "
        "deutlich schneller als gleitende Durchschnitte - und handelt oefter."
    )
    params = (
        Param("fast", 12, "Schnelle EMA", "int", 2, 100),
        Param("slow", 26, "Langsame EMA", "int", 5, 200),
        Param("signal", 9, "Signallinie", "int", 2, 100),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        line, signal, _ = ta.macd(
            df["close"], self.settings["fast"], self.settings["slow"], self.settings["signal"]
        )
        return state_position(line > signal, signal > line)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        line, signal, _ = ta.macd(
            df["close"], self.settings["fast"], self.settings["slow"], self.settings["signal"]
        )
        return {"MACD": line, "Signal": signal}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="state",
            overlay=False,
            inputs=(
                'fastLen = input.int({fast}, "Schnelle EMA", minval=2, group="Strategie")',
                'slowLen = input.int({slow}, "Langsame EMA", minval=5, group="Strategie")',
                'signalLen = input.int({signal}, "Signallinie", minval=2, group="Strategie")',
            ),
            calc=("[macdLine, signalLine, _hist] = ta.macd(close, fastLen, slowLen, signalLen)",),
            long_entry="macdLine > signalLine",
            long_exit="signalLine > macdLine",
            plots=(
                'plot(macdLine, "MACD", color=color.new(#5ce1a6, 0), linewidth=2)',
                'plot(signalLine, "Signal", color=color.new(#f0b232, 0), linewidth=2)',
                'hline(0, "Null", color=color.new(color.gray, 50))',
            ),
        )

    @property
    def label(self) -> str:
        s = self.settings
        return f"MACD Crossover ({s['fast']}/{s['slow']}/{s['signal']})"


@register
class TurtleBreakout(Strategy):
    key = "turtle_breakout"
    display_name = "Turtle Breakout"
    category = "breakout"
    description = (
        "Einstieg beim Ausbruch ueber das 20-Tage-Hoch, Ausstieg unter dem "
        "10-Tage-Tief. Das Originalsystem der Turtle Traders von 1983."
    )
    params = (
        Param("entry", 20, "Ausbruch (Bars)", "int", 2, 300),
        Param("exit", 10, "Ausstieg (Bars)", "int", 2, 300),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        entry_high = ta.rolling_high(df["high"], self.settings["entry"])
        exit_low = ta.rolling_low(df["low"], self.settings["exit"])
        return hold_position(df["close"] > entry_high, df["close"] < exit_low)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {
            f"Hoch {self.settings['entry']}": ta.rolling_high(df["high"], self.settings["entry"]),
            f"Tief {self.settings['exit']}": ta.rolling_low(df["low"], self.settings["exit"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'entryLen = input.int({entry}, "Ausbruch (Bars)", minval=2, group="Strategie")',
                'exitLen = input.int({exit}, "Ausstieg (Bars)", minval=2, group="Strategie")',
            ),
            calc=(
                "// [1] = das Hoch/Tief VOR der laufenden Bar, sonst waere kein Ausbruch moeglich",
                "highestHigh = ta.highest(high, entryLen)",
                "lowestLow = ta.lowest(low, exitLen)",
                "entryHigh = highestHigh[1]",
                "exitLow = lowestLow[1]",
            ),
            long_entry="close > entryHigh",
            long_exit="close < exitLow",
            plots=(
                'plot(entryHigh, "Ausbruchshoch", color=color.new(#5ce1a6, 0))',
                'plot(exitLow, "Ausstiegstief", color=color.new(#ff5c5c, 0))',
            ),
        )

    @property
    def label(self) -> str:
        return f"Turtle Breakout ({self.settings['entry']}/{self.settings['exit']})"


@register
class High52Week(Strategy):
    key = "high_52w"
    display_name = "52-Wochen-Hoch Momentum"
    category = "breakout"
    description = (
        "Kauft neue 52-Wochen-Hochs und haelt, bis der Kurs unter seinen "
        "Tiefpunkt der letzten Wochen faellt. Momentum in Reinform."
    )
    params = (
        Param("lookback", 252, "Hoch-Fenster (Bars)", "int", 20, 1000),
        Param("exit", 50, "Ausstieg-Fenster (Bars)", "int", 5, 500),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high = ta.rolling_high(df["high"], self.settings["lookback"])
        low = ta.rolling_low(df["low"], self.settings["exit"])
        return hold_position(df["close"] >= high, df["close"] < low)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {
            f"Hoch {self.settings['lookback']}": ta.rolling_high(df["high"], self.settings["lookback"]),
            f"Tief {self.settings['exit']}": ta.rolling_low(df["low"], self.settings["exit"]),
        }

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'lookbackLen = input.int({lookback}, "Hoch-Fenster (Bars)", minval=20, group="Strategie")',
                'exitLen = input.int({exit}, "Ausstieg-Fenster (Bars)", minval=5, group="Strategie")',
            ),
            calc=(
                "highestHigh = ta.highest(high, lookbackLen)",
                "lowestLow = ta.lowest(low, exitLen)",
                "breakoutHigh = highestHigh[1]",
                "exitLow = lowestLow[1]",
            ),
            long_entry="close >= breakoutHigh",
            long_exit="close < exitLow",
            plots=(
                'plot(breakoutHigh, "52-Wochen-Hoch", color=color.new(#5ce1a6, 0))',
                'plot(exitLow, "Ausstiegstief", color=color.new(#ff5c5c, 0))',
            ),
        )

    @property
    def label(self) -> str:
        return f"52-Wochen-Hoch ({self.settings['lookback']}/{self.settings['exit']})"


@register
class IchimokuBreakout(Strategy):
    key = "ichimoku"
    display_name = "Ichimoku Cloud Breakout"
    category = "trend"
    description = (
        "Long, wenn der Kurs ueber der Wolke steht und Tenkan ueber Kijun liegt. "
        "Ausstieg, sobald der Kurs in die Wolke zurueckfaellt."
    )
    params = (
        Param("tenkan", 9, "Tenkan", "int", 2, 100),
        Param("kijun", 26, "Kijun", "int", 3, 200),
        Param("senkou_b", 52, "Senkou B", "int", 5, 400),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        s = self.settings
        tenkan, kijun, span_a, span_b = ta.ichimoku(df, s["tenkan"], s["kijun"], s["senkou_b"])
        cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
        cloud_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)

        entry = (df["close"] > cloud_top) & (tenkan > kijun)
        exit_ = df["close"] < cloud_bottom
        return hold_position(entry, exit_)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        s = self.settings
        tenkan, kijun, span_a, span_b = ta.ichimoku(df, s["tenkan"], s["kijun"], s["senkou_b"])
        return {"Tenkan": tenkan, "Kijun": kijun, "Senkou A": span_a, "Senkou B": span_b}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="event",
            inputs=(
                'tenkanLen = input.int({tenkan}, "Tenkan", minval=2, group="Strategie")',
                'kijunLen = input.int({kijun}, "Kijun", minval=3, group="Strategie")',
                'senkouBLen = input.int({senkou_b}, "Senkou B", minval=5, group="Strategie")',
            ),
            calc=(
                "tenkanSen = (ta.highest(high, tenkanLen) + ta.lowest(low, tenkanLen)) / 2",
                "kijunSen = (ta.highest(high, kijunLen) + ta.lowest(low, kijunLen)) / 2",
                "// Die Wolke wird um kijunLen Bars nach vorne projiziert - deshalb [kijunLen]",
                "senkouARaw = (tenkanSen + kijunSen) / 2",
                "senkouBRaw = (ta.highest(high, senkouBLen) + ta.lowest(low, senkouBLen)) / 2",
                "spanA = senkouARaw[kijunLen]",
                "spanB = senkouBRaw[kijunLen]",
                "cloudTop = math.max(spanA, spanB)",
                "cloudBottom = math.min(spanA, spanB)",
            ),
            long_entry="close > cloudTop and tenkanSen > kijunSen",
            long_exit="close < cloudBottom",
            plots=(
                'pA = plot(spanA, "Senkou A", color=color.new(#5ce1a6, 60))',
                'pB = plot(spanB, "Senkou B", color=color.new(#ff5c5c, 60))',
                'fill(pA, pB, color=color.new(#5ce1a6, 88))',
                'plot(tenkanSen, "Tenkan", color=color.new(#7aa2f7, 0))',
                'plot(kijunSen, "Kijun", color=color.new(#f0b232, 0))',
            ),
        )

    @property
    def label(self) -> str:
        s = self.settings
        return f"Ichimoku Cloud ({s['tenkan']}/{s['kijun']}/{s['senkou_b']})"


@register
class SupertrendStrategy(Strategy):
    key = "supertrend"
    display_name = "Supertrend"
    category = "trend"
    description = (
        "Folgt einem ATR-basierten Trailing-Stop und dreht bei jedem Bruch. "
        "Immer im Markt - im Seitwaertsmarkt entsprechend teuer."
    )
    params = (
        Param("length", 10, "ATR-Laenge", "int", 2, 100),
        Param("multiplier", 3.0, "ATR-Faktor", "float", 0.5, 20.0, 0.1),
    )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        _, direction = ta.supertrend(df, self.settings["length"], self.settings["multiplier"])
        return direction.fillna(0.0)

    def indicator_lines(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        line, _ = ta.supertrend(df, self.settings["length"], self.settings["multiplier"])
        return {"Supertrend": line}

    def pine(self) -> PineSpec:
        return PineSpec(
            mode="state",
            inputs=(
                'atrLen = input.int({length}, "ATR-Laenge", minval=2, group="Strategie")',
                'factor = input.float({multiplier}, "ATR-Faktor", minval=0.5, step=0.1, group="Strategie")',
            ),
            calc=(
                "[stLine, stDir] = ta.supertrend(factor, atrLen)",
                "// Achtung: Pine liefert -1 fuer Aufwaerts- und +1 fuer Abwaertstrend",
                "upTrend = stDir < 0",
            ),
            long_entry="upTrend",
            long_exit="not upTrend",
            plots=(
                'plot(stLine, "Supertrend", color=upTrend ? color.new(#5ce1a6, 0) : color.new(#ff5c5c, 0), linewidth=2)',
            ),
        )

    @property
    def label(self) -> str:
        mult = self.settings["multiplier"]
        mult_text = f"{mult:g}"
        return f"Supertrend ({self.settings['length']},{mult_text})"
