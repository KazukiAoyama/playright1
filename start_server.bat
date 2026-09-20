@echo off
setlocal
cd /d "%~dp0"
title Local Reservation Server

echo =========================================================
echo   Starting Local Server (http://localhost:8000)...
echo =========================================================
echo.

start http://localhost:8000
python server.py

pause
