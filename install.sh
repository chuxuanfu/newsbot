#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data logs
PYTHON_BIN="${PYTHON_BIN:-/Users/chuxuanfu/.local/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
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
