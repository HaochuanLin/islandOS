IslandOS Windows portable demo
================================

1. Extract the entire ZIP to a writable folder.
2. Double-click run-demo.bat.
3. Open advisor-report.json to review the four-policy comparison, hourly audit,
   weight-sensitivity analysis, and recommendation for operator review.

Files
-----
islandos-advisor.exe       Validates telemetry and produces dispatch advice.
islandos-gateway.exe       Validates/normalizes telemetry records from files.
islandos-gateway-server.exe Accepts read-only JSON telemetry on loopback HTTP.
run-gateway-server.bat     Starts the local HTTP ingress at 127.0.0.1:8765.
run-synthetic-demo.bat     Sends synthetic hourly samples and opens dashboard.
telemetry_replay_demo.csv  Included example input; not site data.
device_map.example.json    Example vendor field mapping template.
run-demo.bat               Runs the included sample and saves a JSON report.

Local device/gateway integration
--------------------------------
1. Double-click run-gateway-server.bat to start the local HTTP receiver and open the operator dashboard at http://127.0.0.1:8765/dashboard.
2. A device bridge on this same computer can POST one JSON object per sample to
   http://127.0.0.1:8765/telemetry with Content-Type: application/json.
3. GET /health checks process health; GET /latest returns the latest accepted
   sample. Accepted records append to live-telemetry-audit.jsonl.
4. Required canonical fields: timestamp_utc, renewable_surplus_kw,
   water_demand_m3, cooling_demand_kw_th. Timestamp must be fresh (default 300 s).
5. Optional: start the server with --mapping path-to-your-device-map.json to map
   vendor keys and units to the canonical schema.
6. GET /advice returns a recommendation-only report only after at least two
   valid hourly-aligned samples have arrived and the latest sample is fresh.
7. The browser dashboard refreshes every 15 seconds and displays telemetry,
   policy metrics, and constraint warnings. It never sends device commands.
8. This endpoint is local-only and ingest-only. It does not speak Modbus/MQTT,
   write PLC setpoints, or control actuators. Use a site-approved local bridge
   for the device's actual protocol; do not expose this HTTP server to a LAN.

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


One-click synthetic demo
------------------------
Double-click run-synthetic-demo.bat. It starts the gateway with a 90000-second
freshness window and posts 24 hourly synthetic samples. This setting is only for
demo replay; never use it for real sensors. For real local telemetry bridges,
use run-gateway-server.bat, which uses the 300-second default freshness limit.
All synthetic records are labelled synthetic-demo-generator and are not site data.
