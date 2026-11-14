@echo off
title EXVS2 matchmaking server - configure
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure.ps1" %*
echo.
pause
