@echo off
setlocal
cd /d "%~dp0.."
schtasks /End /TN "OpenRemoteHub" >nul 2>&1
".venv\Scripts\python.exe" -c "import sys;sys.path.insert(0,'.');from app import mesh_runtime;mesh_runtime.stop()"
echo 已停止 OpenRemoteHub 与内置 ORN。
