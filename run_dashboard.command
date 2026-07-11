#!/bin/bash
# Double-click this file in Finder to run the dashboard.
# (First time only: right-click -> Open, to bypass Gatekeeper's "unknown developer" warning.)
# A browser tab opens automatically once the local server is up.

# Change this to wherever you put the "strip" folder on your Mac, e.g.:
# cd "/Users/yourname/Desktop/strip"
cd "$(dirname "$0")"

source venv/bin/activate

# Lets Quit close this specific Terminal window/tab afterwards (matched by
# tty, not window title/index, so it can't accidentally close some other
# Terminal window you have open). dashboard.py spawns the actual close
# command itself, fully detached, once the server has shut down -- doing it
# from here instead would still have bash/osascript attached to this window
# at close time, which makes Terminal prompt to confirm terminating them.
export DASHBOARD_TERMINAL_TTY="$(tty)"
python3 dashboard.py
