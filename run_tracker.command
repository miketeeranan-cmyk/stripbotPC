#!/bin/bash
# Double-click this file in Finder to run the tracker.
# (First time only: right-click -> Open, to bypass Gatekeeper's "unknown developer" warning.)

# Change this to wherever you put the "strip" folder on your Mac, e.g.:
# cd "/Users/yourname/Desktop/strip"
cd "$(dirname "$0")"

source venv/bin/activate
python3 stripchat_level_tracker.py

# Keep the Terminal window open after the script exits, like "pause" on Windows
read -p "Press Enter to close..."
