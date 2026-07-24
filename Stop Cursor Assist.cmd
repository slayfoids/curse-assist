@echo off
REM Double-click to stop the background Cursor Assist instance.
cd /d "%~dp0"
py "%~dp0background\stop_hidden.py"
echo.
pause
