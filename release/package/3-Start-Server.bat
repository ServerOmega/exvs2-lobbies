@echo off
title EXVS2 matchmaking server (close this window to stop it)
cd /d "%~dp0server"
if not exist "Server-Infinite.exe" (
  echo The server is not built yet. Double-click 1-Build-Server.bat first.
  pause
  exit /b 1
)
echo Starting the server. Keep this window open while people play. Close it to stop the server.
echo A small notice window pops up for 5 seconds at start - that's normal.
echo Log files: %~dp0server\Logs
echo.
"Server-Infinite.exe"
echo.
echo The server stopped.
pause
