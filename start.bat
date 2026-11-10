@echo off
rem Start the Meal Planner in the background and open it.
rem Safe to run when it is already running. Pass --no-browser to skip opening the page.
cd /d "%~dp0"
uv sync --quiet || goto :failed
if not exist planner.toml copy planner.example.toml planner.toml >nul
".venv\Scripts\python.exe" -m meals.cli status >nul 2>&1 && goto :running
start "Meal Planner" /min ".venv\Scripts\pythonw.exe" -m meals.cli serve
rem Wait up to 15 seconds for it to answer.
for /l %%i in (1,1,15) do (
  timeout /t 1 >nul
  ".venv\Scripts\python.exe" -m meals.cli status >nul 2>&1 && goto :running
)
echo The Meal Planner didn't start. See data\meals.log.
goto :failed
:running
echo Meal Planner is running on http://127.0.0.1:8200/
if /i not "%1"=="--no-browser" start "" http://127.0.0.1:8200/
exit /b 0
:failed
if /i not "%1"=="--no-browser" pause
exit /b 1
