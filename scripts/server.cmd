@echo off
setlocal
cd /d "%~dp0.."
if not exist ".runtime" mkdir ".runtime"
".venv\Scripts\pythonw.exe" scripts\server_windows.py >> ".runtime\server.log" 2>&1
