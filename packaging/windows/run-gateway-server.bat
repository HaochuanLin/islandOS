@echo off
setlocal
set "ROOT=%~dp0"
echo IslandOS read-only telemetry gateway and operator dashboard
echo This service listens only on 127.0.0.1:8765. No PLC commands are supported.
start "IslandOS local gateway" /min "%ROOT%islandos-gateway-server.exe" --host 127.0.0.1 --port 8765 --audit-file "%ROOT%live-telemetry-audit.jsonl"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/dashboard"
echo Dashboard: http://127.0.0.1:8765/dashboard
echo Gateway runs in a minimized console. Close that console to stop it.
pause
