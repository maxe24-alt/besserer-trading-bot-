#!/usr/bin/env bash
# Startet das Dashboard - egal, aus welchem Ordner aufgerufen.
#
#   ./start.sh            Dashboard auf Port 8000
#   ./start.sh 8080       anderer Port
#
# Das Skript wechselt selbst ins Projektverzeichnis und sucht eine
# virtuelle Umgebung. Damit entfallen die beiden haeufigsten Stolpersteine:
# im falschen Ordner stehen und ein nicht aktiviertes venv.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT"

PORT="${1:-8000}"

# --- Python finden -------------------------------------------------------
# Erst eine virtuelle Umgebung im Projekt oder daneben, sonst python3.
PYTHON=""
for candidate in "$PROJECT/.venv" "$PROJECT/venv" "$PROJECT/../.venv" "$PROJECT/../venv"; do
    if [ -x "$candidate/bin/python" ]; then
        PYTHON="$candidate/bin/python"
        echo "Virtuelle Umgebung: $(cd "$candidate" && pwd)"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    if command -v python3 > /dev/null 2>&1; then
        PYTHON="python3"
    elif command -v python > /dev/null 2>&1; then
        PYTHON="python"
    else
        echo "Kein Python gefunden. Auf macOS: 'brew install python3'." >&2
        exit 1
    fi
fi

# --- Abhaengigkeiten pruefen --------------------------------------------
if ! "$PYTHON" -c "import pandas, numpy, requests" > /dev/null 2>&1; then
    echo "Es fehlen noch Pakete. Ich installiere sie einmalig ..."
    "$PYTHON" -m pip install --quiet -r requirements.txt
fi

echo "Projekt: $PROJECT"
echo "Python:  $("$PYTHON" --version)"
echo
exec "$PYTHON" -m backtester dashboard --port "$PORT"
