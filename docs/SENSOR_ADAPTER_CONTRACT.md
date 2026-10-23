# IslandOS sensor adapter contract (v0.1)

## Goal and non-goal

This document defines a stable boundary between physical instrumentation and IslandOS. The contract is designed before hardware is selected, so an adapter can be added later without rewriting dispatch logic.

**Current status:** contract and mock adapter only. No sensor hardware, gateway, serial port, Modbus client, MQTT broker, OPC UA client, or live telemetry connection is implemented. A valid message is not proof that a sensor is calibrated or trustworthy.

## Layered connection model

```text
Sensor / meter / PLC
  -> physical interface (4–20 mA, RS-485, Ethernet, etc.)
  -> vendor device protocol (e.g. Modbus register map, OPC UA node, API)
  -> site gateway / protocol adapter
  -> IslandOS normalized telemetry envelope
  -> schema + freshness + range + provenance checks
  -> offline scenario input
```

A USB/RS-485 converter is only a physical interface; it does not identify register addresses, scaling, byte order, units, calibration, or device semantics. Those must be configured and verified against the device documentation.

## Normalized message

Each sample must contain:

- `schema_version`: contract version.
- `site_id`, `device_id`, `signal_id`: stable identifiers from a reviewed site configuration.
- `observed_at`: ISO-8601 timestamp with UTC offset.
- `value`, `unit`: finite numeric value and an explicitly declared unit.
- `quality`: adapter-level quality such as `good`, `uncertain`, or `bad`.
- `source_type`: `sensor`, `meter`, `plc`, `manual`, `public`, `forecast`, or `synthetic`.
- `raw_reference`: device/register or source record reference for traceability.

Example (illustrative only, not measured data):

```json
{
  "schema_version": "0.1",
  "site_id": "site-demo",
  "device_id": "meter-demo-01",
  "signal_id": "pv_power",
  "observed_at": "2026-10-22T08:00:00+08:00",
  "value": 12.5,
  "unit": "kW",
  "quality": "good",
  "source_type": "sensor",
  "raw_reference": "demo-register-map:40001"
}
```

Never copy the example value into a real scenario. It exists only to show message shape.

## Initial signal registry

| Canonical signal | Unit | Expected meaning | Typical source |
|---|---|---|---|
| `wind_power` | kW | Current measured wind generation | Inverter / meter / SCADA |
| `pv_power` | kW | Current measured PV generation | Inverter / meter / SCADA |
| `critical_load` | kW | Current critical electrical load | Main/sub-meter |
| `reservoir_usable_volume` | m³ | Current usable water inventory, not raw water level | Level sensor plus validated tank geometry, or volume sensor |
| `reservoir_capacity` | m³ | Usable reservoir capacity; normally static asset data | Verified asset register |
| `ro_capacity` | m³/h | RO rated production capacity | Datasheet / commissioning record |
| `ro_specific_energy` | kWh/m³ | RO specific electrical energy consumption | Datasheet or measured operating data with defined boundary |

Water level in metres is not interchangeable with water volume in cubic metres. A validated tank/reservoir level-volume curve is required for conversion.

## Fail-closed rules

- Unknown signal ID or unsupported unit: reject.
- Missing timestamp, unit, device ID, quality, or provenance: reject.
- Non-finite value or physically invalid range: reject.
- Quality is `bad` or `uncertain`: reject for the strict operational snapshot unless a site-approved policy explicitly defines an alternative.
- Stale or future-dated samples: reject according to a site-approved freshness threshold.
- Duplicate samples with conflicting values: quarantine and report; do not silently choose one.
- Missing required critical signals: do not start the scenario.
- Do not replace missing values with zero, carry forward indefinitely, or interpolate without an explicit documented policy.

## Security and operational safety

Read-only telemetry is the default. The adapter contract must not expose arbitrary control writes to field devices. Production integration requires authentication, network segmentation, access control, audit logs, clock synchronization, device-specific testing, failure behavior, and an independent engineering safety review. IslandOS remains a decision-support/offline simulation tool; this contract does not authorize live control.
