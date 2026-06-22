#!/usr/bin/env bash
set -euo pipefail

LABEL="com.chuxuanfu.newsbot"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH"
  echo "Stopped $LABEL"
else
  echo "$LABEL is not running"
fi
