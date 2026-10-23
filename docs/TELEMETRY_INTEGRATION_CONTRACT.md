# islandOS telemetry integration contract (prototype)

## Scope and safety boundary

This document defines the current local HTTP ingress contract. It is a read-only telemetry and recommendation interface: it does not issue PLC setpoints or actuator writes. The example field map is a template, not a certified adapter for a particular vendor or device.

The server refuses non-loopback bind addresses. By default, no bearer-token authentication is enabled; loopback binding is the only built-in network boundary. Do not expose this server to a LAN, the public internet, or an untrusted browser. For a site network, use a site-approved authenticated TLS gateway and review the deployment with the responsible controls/security engineer first.

For local deployments that need an additional access check, set `ISLANDOS_GATEWAY_TOKEN` in the server process environment. When set, all HTTP endpoints require `Authorization: Bearer <token>`; comparisons use a constant-time comparison. The synthetic sender reads the same environment variable and attaches the header automatically. Keep the token out of source control, screenshots, logs, command-line arguments, and shared demo packages.

## Start the local gateway

Optional vendor mapping:

```bash
python islandos_gateway_server.py --host 127.0.0.1 --port 8765 --mapping configs/device_mapping.example.json
```

PowerShell with token protection enabled:

```powershell
$env:ISLANDOS_GATEWAY_TOKEN = "replace-with-a-local-secret"
python islandos_gateway_server.py --host 127.0.0.1 --port 8765 --mapping configs/device_mapping.example.json
```

The example mapping expects source keys `ts`, `solar_power_w`, `water_demand_l`, and `cooling_load_kw_th`. Verify actual sensor documentation before changing the source units, scale, or offset. Required canonical fields are `timestamp_utc` (timezone-aware ISO-8601), `renewable_surplus_kw` (kW), `water_demand_m3` (m3), and `cooling_demand_kw_th` (kW_th). Optional forecast fields are `forecast_surplus_kw` (kW) and `forecast_water_demand_m3` (m3).

## Endpoints

- `GET /health`: service and mapping readiness. Reports whether a mapping is loaded and which canonical fields it defines.
- `POST /telemetry`: accept one JSON object with `Content-Type: application/json`. A successful ingest returns HTTP 202 and an accepted status; invalid telemetry is rejected with HTTP 422 and validation errors.
- `GET /latest`: most recent accepted normalized telemetry record.
- `GET /advice?weight_profile=balanced`: read-only dispatch recommendation. Supported weight profiles are reported by the API error if an unknown profile is supplied.
- `GET /dashboard`: local operator review page.

General responses include `Cache-Control: no-store`; request bodies larger than 65,536 bytes or empty bodies are rejected. An optional bearer token, when configured, protects these endpoints and returns HTTP 401 when missing or invalid. Keep device and sensor timestamps synchronized: messages that are stale or too far in the future are rejected according to the configured freshness window.

## Example request

Without token protection, on a private local development machine only:

```bash
curl -X POST http://127.0.0.1:8765/telemetry \
  -H "Content-Type: application/json" \
  -d '{"timestamp_utc":"2026-10-23T05:00:00Z","renewable_surplus_kw":42,"water_demand_m3":5,"cooling_demand_kw_th":8,"quality_flag":"good"}'
```

With token protection, add `-H "Authorization: Bearer $ISLANDOS_GATEWAY_TOKEN"` (or the platform-equivalent header). Do not paste a real token into public reports or source files.

## Before connecting a real device

- [ ] Confirm protocol, transport, vendor register/field definitions, scaling, offsets, sign conventions, and engineering units.
- [ ] Confirm timestamp timezone, clock synchronization, sample rate, stale-data threshold, and out-of-order behavior.
- [ ] Define valid operating ranges, sensor fault indicators, calibration status, missing-data policy, and quality-flag mapping.
- [ ] Replay captured fixtures offline; include malformed, stale, future-dated, duplicate, missing, negative, and non-finite values.
- [ ] Verify the local gateway and audit directory permissions; rotate and protect audit data according to site policy.
- [ ] Keep the control path disabled. Require a separate hazard review, interlock design, operator authorization, and device-specific acceptance tests before any future actuation work.

The current project does not establish field accuracy, vendor certification, universal plug-and-play compatibility, or permission to control equipment. Synthetic replay verifies software behavior only.
