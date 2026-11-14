@echo off
title EXVS2 matchmaking server - import pictures
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\import-images.ps1" %*
echo.
pause
