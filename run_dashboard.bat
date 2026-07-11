@echo off
REM A browser tab opens automatically once the local server is up.
cd /d "%~dp0"
python dashboard.py
pause
