"""Backtest-Engine, Kennzahlen und Ergebnisstrukturen."""

from .backtest import BacktestConfig, run_backtest, run_strategy
from .gauntlet import GauntletResult, run_gauntlet
from .metrics import compute_metrics
from .results import BacktestResult, Metrics, Trade

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "GauntletResult",
    "Metrics",
    "Trade",
    "compute_metrics",
    "run_backtest",
    "run_gauntlet",
    "run_strategy",
]
