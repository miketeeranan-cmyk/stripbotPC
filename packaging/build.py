"""
Build the StripTracker desktop app with PyInstaller.

Produces two separate builds:
  - StripTrackerCore: the real app (dashboard.py + templates/static). This is
    what the launcher downloads and swaps in on every update.
  - StripTracker: the launcher (launcher.py). Installed once by hand; rarely
    rebuilt since it isn't part of the auto-update payload.

Usage (from anywhere -- paths are resolved relative to this file):
    python packaging/build.py            # both
    python packaging/build.py --core     # StripTrackerCore only
    python packaging/build.py --launcher # StripTracker (launcher) only

Output lands in dist/ at the repo root. On macOS, --windowed produces a
.app bundle; on Windows it produces a folder containing the .exe.
"""

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_SEP = ";" if sys.platform == "win32" else ":"


def _run(args):
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def build_core():
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name",
            "StripTrackerCore",
            f"--add-data=templates{DATA_SEP}templates",
            f"--add-data=static{DATA_SEP}static",
            "dashboard.py",
        ]
    )


def build_launcher():
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name",
            "StripTracker",
            "launcher.py",
        ]
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--core" in args:
        build_core()
    if not args or "--launcher" in args:
        build_launcher()
