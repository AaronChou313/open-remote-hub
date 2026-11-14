@echo off
schtasks /Run /TN "OpenRemoteHub" >nul 2>&1
echo 已请求启动 OpenRemoteHub，稍后打开 http://127.0.0.1:8765/
