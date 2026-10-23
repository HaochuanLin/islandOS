@echo off
setlocal
set "ROOT=%~dp0"
echo IslandOS offline telemetry replay and dispatch advice demo
echo This uses the included synthetic/example telemetry file, not live hardware.
"%ROOT%islandos-advisor.exe" "%ROOT%telemetry_replay_demo.csv" --max-age-seconds 7200 --received-at 2026-10-23T07:00:00Z --output "%ROOT%advisor-report.json"
if errorlevel 1 (
  echo Demo failed. Review the error above and README.txt.
  pause
  exit /b 1
)
echo.
echo Report created: "%ROOT%advisor-report.json"
echo No PLC commands or actuator writes are performed.
pause
