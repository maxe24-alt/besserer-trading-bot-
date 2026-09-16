"""Kontraktspezifikationen fuer Futures, ETFs und Krypto.

Die Angaben bestimmen, wie aus Punkten Dollar werden. Fuer ES ist ein
Indexpunkt 50 USD wert, fuer NQ 20 USD. Bei Aktien/ETFs ist der Multiplikator
1, ein "Punkt" ist dort schlicht ein Dollar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    """Alles, was die Engine ueber ein handelbares Symbol wissen muss."""

    symbol: str
    name: str
    kind: str  # "future" | "etf" | "crypto" | "stock"
    point_value: float = 1.0  # USD je Punkt je Kontrakt
    tick_size: float = 0.01
    commission_per_contract: float = 0.0  # USD je Kontrakt je Seite
    currency: str = "USD"
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tick_value(self) -> float:
        return self.tick_size * self.point_value


_INSTRUMENTS: list[Instrument] = [
    Instrument(
        symbol="ES=F",
        name="E-mini S&P 500",
        kind="future",
        point_value=50.0,
        tick_size=0.25,
        commission_per_contract=2.25,
        aliases=("ES", "ES=F", "SP500-FUT"),
    ),
    Instrument(
        symbol="NQ=F",
        name="E-mini Nasdaq 100",
        kind="future",
        point_value=20.0,
        tick_size=0.25,
        commission_per_contract=2.25,
        aliases=("NQ", "NQ=F", "NASDAQ-FUT"),
    ),
    Instrument(
        symbol="MES=F",
        name="Micro E-mini S&P 500",
        kind="future",
        point_value=5.0,
        tick_size=0.25,
        commission_per_contract=0.52,
        aliases=("MES", "MES=F"),
    ),
    Instrument(
        symbol="MNQ=F",
        name="Micro E-mini Nasdaq 100",
        kind="future",
        point_value=2.0,
        tick_size=0.25,
        commission_per_contract=0.52,
        aliases=("MNQ", "MNQ=F"),
    ),
    Instrument(
        symbol="YM=F",
        name="E-mini Dow",
        kind="future",
        point_value=5.0,
        tick_size=1.0,
        commission_per_contract=2.25,
        aliases=("YM", "YM=F"),
    ),
    Instrument(
        symbol="RTY=F",
        name="E-mini Russell 2000",
        kind="future",
        point_value=50.0,
        tick_size=0.1,
        commission_per_contract=2.25,
        aliases=("RTY", "RTY=F"),
    ),
    Instrument(
        symbol="GC=F",
        name="Gold Futures",
        kind="future",
        point_value=100.0,
        tick_size=0.1,
        commission_per_contract=2.50,
        aliases=("GC", "GC=F", "GOLD"),
    ),
    Instrument(
        symbol="CL=F",
        name="Crude Oil Futures",
        kind="future",
        point_value=1000.0,
        tick_size=0.01,
        commission_per_contract=2.50,
        aliases=("CL", "CL=F", "OIL"),
    ),
    Instrument(symbol="SPY", name="SPDR S&P 500 ETF", kind="etf", tick_size=0.01),
    Instrument(symbol="QQQ", name="Invesco QQQ ETF", kind="etf", tick_size=0.01),
    Instrument(symbol="IWM", name="iShares Russell 2000 ETF", kind="etf", tick_size=0.01),
    Instrument(symbol="BTC-USD", name="Bitcoin", kind="crypto", tick_size=0.01),
    Instrument(symbol="ETH-USD", name="Ethereum", kind="crypto", tick_size=0.01),
]

_BY_KEY: dict[str, Instrument] = {}
for _inst in _INSTRUMENTS:
    _BY_KEY[_inst.symbol.upper()] = _inst
    for _alias in _inst.aliases:
        _BY_KEY[_alias.upper()] = _inst


def resolve(symbol: str) -> Instrument:
    """Liefert die Kontraktspezifikation zu einem Symbol.

    Unbekannte Symbole werden als generische Aktie mit Multiplikator 1
    behandelt, damit beliebige Ticker ohne Konfiguration funktionieren.
    """
    key = (symbol or "").strip().upper()
    if key in _BY_KEY:
        return _BY_KEY[key]
    return Instrument(symbol=key or "UNKNOWN", name=key or "Unknown", kind="stock")


def canonical_symbol(symbol: str) -> str:
    """Uebersetzt Kurzformen wie "ES" in das Provider-Symbol "ES=F"."""
    return resolve(symbol).symbol


def known_instruments() -> list[Instrument]:
    return list(_INSTRUMENTS)
