@echo off
rem Belfort AI: starts the backend and opens the app window. Double-click, or use the Desktop shortcut.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe belfort.py
