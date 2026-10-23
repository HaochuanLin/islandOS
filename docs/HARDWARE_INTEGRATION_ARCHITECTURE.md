# Hardware integration architecture: recommendation-first islandOS

## Design goal

islandOS should be installable before a site-specific device vendor or historian is known. Keep the dispatch core vendor-neutral and isolate field integration behind adapters. A site supplies a device map and units; it should not need a new optimization algorithm for every sensor brand.

## Data path

```text
Sensors / PLC / gateway
        |
        v
Read-only adapter (Modbus TCP, MQTT, serial, vendor API)
        |
        v
Canonical telemetry message + timestamp + device identity + quality
        |
        v
Freshness / range / unit / plausibility checks
        |
        v
islandOS dispatch recommendation + explanation + confidence / constraints
        |
        v
Operator review and acknowledgement
        |
        v
Optional site-approved command adapter (separate deployment and permission)
```

The current repository implements the canonical validation and fail-closed authorization boundary in `islandos_io.py`. It intentionally does not open a hardware connection or write registers. Concrete transport adapters remain separate implementations and must map vendor-specific registers/topics to canonical units.

## Canonical telemetry message

Required fields by default:

| Field | Unit | Meaning |
|---|---|---|
| `timestamp_utc` | ISO-8601 with timezone | Source measurement time, not receipt time |
| `renewable_surplus_kw` | kW | Usable surplus after essential loads/reserves, defined by the site mapping |
| `water_demand_m3` | m³ per interval | Water demand over the model interval |
| `cooling_demand_kw_th` | kW thermal | Cooling demand over the model interval |

Recommended metadata: `device_id`, `quality_flag`, `sequence_number`, `unit_map_version`, and gateway/source identity. The validator rejects stale/future timestamps, missing required fields, non-finite values, negative values for the default demand/surplus fields, and explicitly bad source-quality flags. Missing device identity is a warning, not cryptographic authentication. Never silently impute a failed sensor and then treat the frame as valid.

## Recommendation-only operating mode

- Default to read-only, dry-run recommendations. No transport adapter is opened by the dispatch core.
- Each recommendation records its command name, requested setpoint, unit, rationale, source/model version, timestamp, and that an operator action is required.
- The authorization function denies by default. It requires validated fresh telemetry, a separately enabled write path, explicit operator confirmation, no emergency stop, no manual override, configured operating bounds, and ramp-limit checks when configured.
- An authorization decision is **not** a hardware write and is not a safety certification. The site PLC, hardwired interlocks, and independent protection systems remain authoritative.
- Do not connect write-enabled control to a live asset until a qualified site engineer has approved the point map, units, fail-safe states, command limits, watchdog behavior, network segmentation, authentication, audit retention, and rollback procedure.

## Adapter contract for a future device driver

Implement a transport-specific component that:
1. Reads data and emits the canonical telemetry fields.
2. Declares the register/topic map and unit conversion in a versioned configuration file.
3. Exposes connection health, timestamp age, quality flags, and parse errors.
4. Supports a read-only commissioning mode and deterministic replay from recorded messages.
5. Does not contain dispatch policy or silently bypass the shared validator.
6. Keeps write support disabled unless a site-specific deployment enables it explicitly.

Suggested first integration sequence: CSV replay -> simulated gateway -> read-only Modbus/MQTT adapter -> operator-in-the-loop recommendation -> site-approved command adapter. A generic USB/serial/PLC connection cannot be promised without knowing the device protocol, electrical interface, point map, and vendor access.

## Current evidence and limitations

CI tests cover timestamp freshness, malformed/missing/non-finite telemetry, device quality flags, default-deny behavior, emergency stop, manual override, operator confirmation, bounds, ramp limits, and recommendation audit fields. These are software-level checks, not hardware-in-the-loop tests. The current system has no validated site point map, device credentials, PLC integration, certified safety layer, or real-island acceptance test. Public and synthetic datasets are useful for development and benchmarking but must be labeled with source, license, coverage, missingness, and known quality limitations.


## Local replay gateway

The command-line adapter can replay either CSV or newline-delimited JSON through the exact same telemetry validator used by the safety boundary:

\`\`\`bash
python islandos_gateway.py data/examples/telemetry.csv --format csv --output build/telemetry/audit.jsonl
python islandos_gateway.py data/examples/telemetry.jsonl --format jsonl --output build/telemetry/audit.jsonl
python islandos_gateway.py vendor-export.jsonl --mapping config/device_map.example.json --output build/telemetry/mapped-audit.jsonl
\`\`\`

For deterministic recorded-data tests, supply \`--received-at 2026-10-23T05:00:00Z\`. Invalid rows are still written to the audit output, but the process exits with code 2 so a scheduler or integration harness can detect a rejected batch. The gateway does not issue control commands.


## Portable Windows tool

A separate GitHub Actions workflow builds `islandos-gateway.exe` with PyInstaller on Windows and runs its `--help` smoke test. After the workflow succeeds, download the `islandos-gateway-windows-x64` artifact from the workflow run. This executable validates and audits CSV/JSONL telemetry; it is not a PLC driver and does not issue control commands. The build artifact is generated by CI, not committed into source control.


## Local web deployment

`Dockerfile` packages the Streamlit planning UI and its Python dependencies. `docker-compose.yml` binds the app to `127.0.0.1:8501` only. The container workflow builds the image and checks `/_stcore/health`. This proves the web process starts in CI; it is not a security review, live-device connection test, or field validation. Add authentication and network controls before any non-local exposure.


## End-to-end recommendation CLI

`islandos_advisor.py` accepts recorded telemetry CSV/JSONL, runs the shared quality gate and device mapping, converts valid hourly rows to the dispatch schema, evaluates rolling and fixed-priority strategies, and writes policy summaries plus per-hour audit rows. The chosen policy is a recommendation for operator review under the declared score weights; it is not a command. CI smoke-tests this path with synthetic data and uploads the resulting JSON report. The Windows workflow builds both the telemetry gateway and the advisor executable.
