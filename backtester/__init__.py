"""backtester - Ein Backtesting-Framework fuer Trading-Strategien.

Kernbausteine:
    backtester.data        Marktdaten-Provider (Yahoo, CSV, Databento, ...)
    backtester.strategies  Strategie-Registry mit 12 eingebauten Strategien
    backtester.engine      Backtest-Engine und Kennzahlen
    backtester.cli         Kommandozeile
    backtester.server      Dashboard-Webserver
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
