@echo off
setlocal
set "ROOT=%~dp0"
echo ISLANDOS SYNTHETIC DEMO ONLY - NOT REAL SITE TELEMETRY
echo Starts a loopback-only gateway with a permissive freshness window for replay.
start "IslandOS synthetic demo gateway" /min "%ROOT%islandos-gateway-server.exe" --host 127.0.0.1 --port 8765 --max-age-seconds 90000 --audit-file "%ROOT%synthetic-demo-audit.jsonl"
timeout /t 2 /nobreak >nul
"%ROOT%islandos-telemetry-demo.exe" --url http://127.0.0.1:8765 --hours 24
if errorlevel 1 (
  echo Demo sample upload failed. Check that port 8765 is available.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8765/dashboard"
echo Dashboard opened. All input samples are synthetic and not site data.
echo Close the minimized gateway console to stop the local service.
pause
