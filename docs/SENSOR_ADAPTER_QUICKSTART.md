# Sensor adapter quickstart

## What is ready now

- Stable normalized message format in `islandos_sensors/contract.py`.
- Basic checks for required fields, supported signal names/units, finite non-negative values, timestamp offset, freshness, and quality.
- Explicitly synthetic mock source and examples.
- A documented adapter contract for future hardware-specific drivers.

## What is not ready

There is no live serial, Modbus, MQTT, OPC UA, PLC, or vendor API connection. No sensor has been tested or certified. A hardware-specific adapter cannot be written correctly until we know the exact model, protocol, register map/API, scaling, units, and gateway environment.

## Try the contract locally

```bash
python -m unittest tests.test_sensor_contract -v
```

Example use:

```python
from datetime import datetime, timezone
from islandos_sensors.contract import validate_message
from islandos_sensors.mock_source import make_mock_message

message = make_mock_message("pv_power", 12.5, "kW")
errors = validate_message(message, now=datetime.now(timezone.utc))
if errors:
    raise ValueError("Reject telemetry: " + "; ".join(errors))
print("Contract valid; this remains synthetic test data, not a real measurement.")
```

## How to connect a real device later

1. Identify the actual instrument and gateway model.
2. Obtain vendor documentation: physical interface, protocol, address/register/node, scaling, byte order, update rate, quality flags, and timestamp behavior.
3. Implement a read-only adapter that converts raw device output to the normalized message contract.
4. Add recorded fixtures from the device documentation and unit/integration tests; do not put site credentials or sensitive logs in GitHub.
5. Verify the device's units, calibration, clock, range, and failure behavior with the site engineer.
6. Only then wire approved normalized signals into the site CSV/snapshot ingestion path. Until that integration is explicitly implemented and tested, the readiness form remains manual input.

For water storage, do not map a level sensor's `m` reading directly to `m3`. Use a verified level-volume curve or a volume-capable instrument and document the conversion.

Production deployments should start read-only, use least privilege and network segmentation, and never expose arbitrary writes to PLCs or field equipment. Passing schema validation is not a safety certification or authorization for live control.
