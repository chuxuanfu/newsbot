#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data/maps logs

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "python3 was not found."
  echo "Install Python 3.11+ first, then rerun: bash install.sh"
  echo "macOS Homebrew option: brew install python"
  echo "Manual option: install from https://www.python.org/downloads/"
  echo "Custom path option: PYTHON_BIN=/path/to/python3 bash install.sh"
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Python 3.11+ is required. Found: $("$PYTHON_BIN" --version 2>&1)"
  echo "Install a newer Python, or run with PYTHON_BIN=/path/to/python3.11 bash install.sh"
  exit 1
fi

"$PYTHON_BIN" -m venv --clear .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
fi

python -m app.main init-db
echo "Installed. Edit .env, then run: . .venv/bin/activate && python -m app.main test-telegram"
