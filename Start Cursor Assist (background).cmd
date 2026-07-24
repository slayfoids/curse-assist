@echo off
REM Double-click to launch Cursor Assist in the background (no console window).
REM This window closes itself immediately; the app keeps running.
cd /d "%~dp0"
start "" pythonw "%~dp0background\start_hidden.py"
exit
