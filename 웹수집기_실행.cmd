@echo off
cd /d "%~dp0"
start "" /b ".venv\Scripts\pythonw.exe" -W ignore -m src.web_sync --no-ai
