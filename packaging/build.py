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

# PyInstaller can't reliably infer the target architecture when the running
# Python is an x86_64 process under Rosetta 2 on Apple Silicon hardware (our
# CI runner: arm64 host, x86_64 Python to match the operator's Intel Mac) --
# it needs to be told explicitly, or the build fails outright.
TARGET_ARCH_FLAGS = ["--target-architecture=x86_64"] if sys.platform == "darwin" else []

# pywebview's Windows backend (edgechromium, via pythonnet) dispatches to
# platform submodules and a compiled .NET runtime bridge that PyInstaller's
# import scanner can't find on its own -- --collect-all is what actually
# makes the frozen build import `webview` successfully, not just
# --hidden-import.
WEBVIEW_FLAGS = ["--collect-all=pywebview", "--collect-all=pythonnet"] if sys.platform == "win32" else []

# selenium/webdriver_manager reach submodules (e.g. selenium.webdriver.chrome
# .options, via webdriver.ChromeOptions()) through attribute access rather
# than a direct import, which PyInstaller's static scanner doesn't follow --
# without --collect-all the frozen build fails at runtime with
# "No module named selenium.webdriver...".
SELENIUM_FLAGS = ["--collect-all=selenium", "--collect-all=webdriver_manager"]


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
            *TARGET_ARCH_FLAGS,
            *WEBVIEW_FLAGS,
            *SELENIUM_FLAGS,
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
            *TARGET_ARCH_FLAGS,
            "launcher.py",
        ]
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--core" in args:
        build_core()
    if not args or "--launcher" in args:
        build_launcher()
