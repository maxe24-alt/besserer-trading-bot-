"""Die Backtest-Engine.

Ablauf je Bar:

1. Die Strategie entscheidet am **Schluss** der Bar ueber die Zielposition.
2. Die Engine setzt diese Entscheidung zur **Eroeffnung der naechsten Bar** um.
3. Danach wird die Position zum Schlusskurs bewertet.

Dieser Versatz um eine Bar ist der Grund, warum hier keine Strategie in die
Zukunft schauen kann - auch dann nicht, wenn ihr Indikator es koennte.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..data import bars_per_year, load_bars
from ..instruments import Instrument, resolve
from ..strategies import Strategy, get as get_strategy
from .metrics import compute_metrics
from .results import BacktestResult, Trade


@dataclass
class BacktestConfig:
    """Alle Stellschrauben eines Laufs."""

    initial_capital: float = 100_000.0
    fee_pct: float = 0.1  # Prozent des Volumens je Seite
    commission_per_contract: float | None = None  # None = Vorgabe des Instruments
    slippage_ticks: float = 1.0
    sizing: str = "equity_pct"  # "equity_pct" | "contracts"
    exposure: float = 1.0  # Anteil des Kapitals bei sizing="equity_pct"
    contracts: float = 1.0  # feste Kontraktzahl bei sizing="contracts"
    long_only: bool = True
    risk_free_rate: float = 0.0
    compounding: bool = True  # Positionsgroesse mit dem Konto mitwachsen lassen

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital muss groesser als 0 sein")
        if self.sizing not in {"equity_pct", "contracts"}:
            raise ValueError(f"sizing muss 'equity_pct' oder 'contracts' sein, nicht {self.sizing!r}")
        if self.exposure <= 0:
            raise ValueError("exposure muss groesser als 0 sein")
        if self.fee_pct < 0 or self.slippage_ticks < 0:
            raise ValueError("Gebuehren und Slippage duerfen nicht negativ sein")


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy | str,
    symbol: str = "",
    interval: str = "1d",
    config: BacktestConfig | None = None,
    **strategy_params: Any,
) -> BacktestResult:
    """Fuehrt eine Strategie auf einem Datensatz aus.

    Args:
        df: OHLCV-Bars mit UTC-Index.
        strategy: Instanz oder Registry-Key.
        symbol: Ticker - bestimmt Punktwert und Tickgroesse.
        interval: Bar-Intervall, nur zur Dokumentation im Ergebnis.
        config: Kapital, Gebuehren, Positionsgroesse.
        **strategy_params: Parameter, falls ``strategy`` ein Key ist.

    Returns:
        ``BacktestResult`` mit Kennzahlen, Equity-Kurve und Trades.
    """
    cfg = config or BacktestConfig()
    cfg.validate()

    if isinstance(strategy, str):
        strategy = get_strategy(strategy, **strategy_params)
    if len(df) < 2:
        raise ValueError("Fuer einen Backtest werden mindestens zwei Bars gebraucht")

    instrument = resolve(symbol or "UNKNOWN")
    target = strategy.signals(df)
    if cfg.long_only:
        target = target.clip(lower=0)

    equity, positions, trades, total_fees = _simulate(df, target, instrument, cfg)

    metrics = compute_metrics(
        equity=equity,
        trades=trades,
        positions=positions,
        initial_capital=cfg.initial_capital,
        periods_per_year=bars_per_year(df),
        risk_free_rate=cfg.risk_free_rate,
        total_fees=total_fees,
    )

    return BacktestResult(
        strategy_key=strategy.key,
        strategy_label=strategy.label,
        symbol=instrument.symbol,
        interval=interval,
        start=df.index[0],
        end=df.index[-1],
        initial_capital=cfg.initial_capital,
        metrics=metrics,
        equity=equity,
        positions=positions,
        trades=trades,
        params=dict(strategy.settings),
        category=strategy.category,
    )


def _simulate(
    df: pd.DataFrame,
    target: pd.Series,
    instrument: Instrument,
    cfg: BacktestConfig,
) -> tuple[pd.Series, pd.Series, list[Trade], float]:
    """Der eigentliche Bar-fuer-Bar-Durchlauf."""
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    index = df.index

    # Die Entscheidung von Bar i-1 wird auf Bar i ausgefuehrt.
    desired = target.shift(1).fillna(0).to_numpy(dtype=int)

    point_value = instrument.point_value
    tick = instrument.tick_size
    commission = (
        cfg.commission_per_contract
        if cfg.commission_per_contract is not None
        else instrument.commission_per_contract
    )
    slip = cfg.slippage_ticks * tick

    n = len(df)
    equity_curve = np.empty(n, dtype=float)
    position_curve = np.zeros(n, dtype=float)

    realized_equity = cfg.initial_capital  # Kontostand ohne offene Position
    units = 0.0  # signierte Kontraktzahl
    direction = 0
    entry_price = 0.0
    entry_index = 0
    entry_fees = 0.0
    best = 0.0
    worst = 0.0

    trades: list[Trade] = []
    total_fees = 0.0

    def fill_price(reference: float, side: int) -> float:
        """Slippage geht immer gegen uns: Kauf teurer, Verkauf billiger."""
        return reference + side * slip

    def cost(units_abs: float, price: float) -> float:
        notional = units_abs * price * point_value
        return notional * (cfg.fee_pct / 100.0) + units_abs * commission

    for i in range(n):
        want = int(desired[i])  # numpy-Skalar -> int, sonst stolpert JSON darueber

        # --- 1. Position anpassen, zur Eroeffnung dieser Bar ---
        if want != direction:
            if direction != 0:
                exit_px = fill_price(opens[i], -direction)
                exit_fee = cost(abs(units), exit_px)
                gross = units * (exit_px - entry_price) * point_value
                fees = entry_fees + exit_fee
                total_fees += exit_fee

                realized_equity += gross - fees
                invested = abs(units) * entry_price * point_value
                trades.append(
                    Trade(
                        entry_time=index[entry_index],
                        exit_time=index[i],
                        direction=direction,
                        units=round(abs(units), 6),
                        entry_price=round(entry_price, 4),
                        exit_price=round(exit_px, 4),
                        gross_pnl=round(gross, 2),
                        fees=round(fees, 2),
                        net_pnl=round(gross - fees, 2),
                        bars_held=i - entry_index,
                        return_pct=round((gross - fees) / invested * 100.0, 4) if invested else 0.0,
                        mae=round(worst, 2),
                        mfe=round(best, 2),
                    )
                )
                units, direction = 0.0, 0

            if want != 0:
                entry_px = fill_price(opens[i], want)
                size_base = realized_equity if cfg.compounding else cfg.initial_capital
                units = _position_size(size_base, entry_px, point_value, cfg) * want
                if abs(units) > 0:
                    direction = want
                    entry_price = entry_px
                    entry_index = i
                    entry_fees = cost(abs(units), entry_px)
                    total_fees += entry_fees
                    best = worst = 0.0
                else:
                    units = 0.0

        # --- 2. Position zum Schluss bewerten ---
        if direction != 0:
            open_pnl = units * (closes[i] - entry_price) * point_value
            # MFE/MAE anhand der Extreme der Bar, nicht nur des Schlusskurses.
            if direction > 0:
                best = max(best, units * (highs[i] - entry_price) * point_value)
                worst = min(worst, units * (lows[i] - entry_price) * point_value)
            else:
                best = max(best, units * (lows[i] - entry_price) * point_value)
                worst = min(worst, units * (highs[i] - entry_price) * point_value)
            equity_curve[i] = realized_equity + open_pnl - entry_fees
        else:
            equity_curve[i] = realized_equity

        position_curve[i] = units

    # Offene Position am Ende zum letzten Schlusskurs glattstellen.
    if direction != 0:
        exit_px = fill_price(closes[-1], -direction)
        exit_fee = cost(abs(units), exit_px)
        gross = units * (exit_px - entry_price) * point_value
        fees = entry_fees + exit_fee
        total_fees += exit_fee
        realized_equity += gross - fees
        invested = abs(units) * entry_price * point_value
        trades.append(
            Trade(
                entry_time=index[entry_index],
                exit_time=index[-1],
                direction=direction,
                units=round(abs(units), 6),
                entry_price=round(entry_price, 4),
                exit_price=round(exit_px, 4),
                gross_pnl=round(gross, 2),
                fees=round(fees, 2),
                net_pnl=round(gross - fees, 2),
                bars_held=(n - 1) - entry_index,
                return_pct=round((gross - fees) / invested * 100.0, 4) if invested else 0.0,
                mae=round(worst, 2),
                mfe=round(best, 2),
                exit_reason="end-of-data",
            )
        )
        equity_curve[-1] = realized_equity

    return (
        pd.Series(equity_curve, index=index, name="equity"),
        pd.Series(position_curve, index=index, name="position"),
        trades,
        total_fees,
    )


def _position_size(equity: float, price: float, point_value: float, cfg: BacktestConfig) -> float:
    """Positionsgroesse in Kontrakten (bzw. Stueck bei Aktien)."""
    if cfg.sizing == "contracts":
        return float(cfg.contracts)

    notional_per_contract = price * point_value
    if notional_per_contract <= 0:
        return 0.0
    return max(equity, 0.0) * cfg.exposure / notional_per_contract


def run_strategy(
    symbol: str,
    strategy: str,
    start: str | dt.datetime = "2015-01-01",
    end: str | dt.datetime | None = None,
    interval: str = "1d",
    provider: str = "yahoo",
    config: BacktestConfig | None = None,
    use_cache: bool = True,
    **strategy_params: Any,
) -> BacktestResult:
    """Komfort-Wrapper: Daten laden und eine Strategie darauf laufen lassen."""
    df = load_bars(symbol, start, end, interval, provider=provider, use_cache=use_cache)
    return run_backtest(df, strategy, symbol=symbol, interval=interval, config=config, **strategy_params)
