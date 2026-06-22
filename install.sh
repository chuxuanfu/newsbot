#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data logs

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "python3 was not found. Install Python 3.11+ first, or run with PYTHON_BIN=/path/to/python3 bash install.sh"
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
