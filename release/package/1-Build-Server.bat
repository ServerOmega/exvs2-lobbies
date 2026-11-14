@echo off
title EXVS2 matchmaking server - build
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-server.ps1" %*
echo.
pause
