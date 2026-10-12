@echo off
title RepoAtlas server  (close this window to stop it)
rem Double-click to start RepoAtlas on http://127.0.0.1:8000 and open it in the browser.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo No virtual environment yet. Set it up once, from the repository folder:
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  echo Then double-click this file again.
  pause
  exit /b 1
)
echo.
echo  Starting RepoAtlas on http://127.0.0.1:8000
echo  Keep this window open. Close it, or press Ctrl+C, to stop the server.
echo.
rem Open the browser a few seconds later, once the server is up.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
echo.
echo  The server stopped. If it said "address already in use", RepoAtlas is
echo  probably already running in another window: open http://127.0.0.1:8000
pause
