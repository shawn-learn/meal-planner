@echo off
rem Start the Meal Planner in the background and open it. Safe to run when it is already running.
cd /d "%~dp0"
uv sync --quiet || goto :failed
if not exist planner.toml copy planner.example.toml planner.toml >nul
start "Meal Planner" /min ".venv\Scripts\pythonw.exe" -m meals.cli serve
if /i not "%1"=="--no-browser" (
  timeout /t 3 >nul
  start "" http://127.0.0.1:8200/
)
exit /b 0
:failed
pause
exit /b 1
