@echo off
title RepoAtlas tests
rem Double-click to run the automated test suite (about 15 seconds).
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo No virtual environment yet. See scripts\start-windows.bat for the one-time setup.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q
echo.
pause
