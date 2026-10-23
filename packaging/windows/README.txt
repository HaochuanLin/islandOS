IslandOS Windows portable demo
================================

1. Extract the entire ZIP to a writable folder.
2. Double-click run-demo.bat.
3. Open advisor-report.json to review the four-policy comparison, hourly audit,
   weight-sensitivity analysis, and recommendation for operator review.

Files
-----
islandos-advisor.exe       Validates telemetry and produces dispatch advice.
islandos-gateway.exe       Validates/normalizes telemetry records.
telemetry_replay_demo.csv  Included example input; not site data.
device_map.example.json    Example vendor field mapping template.
run-demo.bat               Runs the included sample and saves a JSON report.

Important limitations
---------------------
- The included data is an example/synthetic replay fixture, not real island data.
- This package does not connect to sensors, PLCs, or actuators.
- It does not send setpoints or control commands.
- The recommendation is advisory only. Check telemetry, forecast quality, local
  operating limits, and safety procedures before making operational decisions.
- A real integration requires a site-approved protocol adapter, point mapping,
  authentication/network controls, interlocks, and hardware-in-the-loop testing.

For the local web model, see the project README and Docker Compose instructions.
