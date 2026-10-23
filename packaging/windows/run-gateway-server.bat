@echo off
setlocal
set "ROOT=%~dp0"
echo IslandOS read-only HTTP telemetry gateway
echo Listening only on 127.0.0.1:8765. No PLC commands are supported.
"%ROOT%islandos-gateway-server.exe" --host 127.0.0.1 --port 8765 --audit-file "%ROOT%live-telemetry-audit.jsonl"
pause
