#!/usr/bin/env bash
set -euo pipefail

NEWSBOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.chuxuanfu.newsbot"
PLIST_TEMPLATE="$NEWSBOT_DIR/launchd/$LABEL.plist.template"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVICE="gui/$(id -u)/$LABEL"

if [ ! -f "$NEWSBOT_DIR/.env" ]; then
  echo "Missing .env. Create it from .env.example and fill TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID."
  exit 1
fi

if [ ! -x "$NEWSBOT_DIR/.venv/bin/python" ]; then
  echo "Missing virtualenv. Run: PYTHON_BIN=/Users/chuxuanfu/.local/bin/python3 bash install.sh"
  exit 1
fi

mkdir -p "$NEWSBOT_DIR/logs" "$HOME/Library/LaunchAgents"

sed "s|__NEWSBOT_DIR__|$NEWSBOT_DIR|g" "$PLIST_TEMPLATE" > "$PLIST_PATH"

if launchctl print "$SERVICE" >/dev/null 2>&1; then
  echo "Existing service found. Restarting $LABEL..."
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" || true
fi

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "$SERVICE"
launchctl kickstart -k "$SERVICE"

echo "Started $LABEL"
echo
echo "Status:"
launchctl print "$SERVICE" | sed -n '1,40p'
echo
echo "Logs:"
echo "  tail -f $NEWSBOT_DIR/logs/newsbot.out.log"
echo "  tail -f $NEWSBOT_DIR/logs/newsbot.err.log"
echo
echo "Stop:"
echo "  launchctl bootout gui/$(id -u) $PLIST_PATH"
