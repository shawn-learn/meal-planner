@echo off
rem Stop the Meal Planner that start.bat started.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m meals.cli stop
if errorlevel 1 pause
