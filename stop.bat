@echo off
rem Stop the Meal Planner.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m meals.cli stop
timeout /t 2 >nul
