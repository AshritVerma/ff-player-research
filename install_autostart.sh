#!/bin/bash
# Install the draft helper as a macOS login agent, so it is simply always
# running and no draft ever starts with "wait, did I start the helper?".
#
#   ./install_autostart.sh              install and start it now
#   ./install_autostart.sh --uninstall  remove it
#
# The Desktop app also starts the helper on demand, so this is optional --
# it just means the helper is up before you open anything at all.

set -e
LABEL="com.ashritverma.ffdrafthelper"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$(command -v python3 || echo /usr/bin/python3)"

if [ "$1" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed. The Desktop app will still start the helper when you open it."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/draft_sync.py</string>
    <string>--room-only</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$REPO/.helper.log</string>
  <key>StandardErrorPath</key><string>$REPO/.helper.log</string>
</dict>
</plist>
PLIST

# reload cleanly whether or not it was already installed
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load "$PLIST"

printf 'waiting for the helper'
for i in $(seq 1 20); do
  if curl -s -m 1 -o /dev/null http://127.0.0.1:8787/api/draft; then
    echo; echo "Running. It will start again at every login, and restart if it ever dies."
    echo "Log: $REPO/.helper.log"
    exit 0
  fi
  printf '.'; sleep 0.5
done
echo
echo "Installed, but it did not answer on 127.0.0.1:8787 -- check $REPO/.helper.log" >&2
exit 1
