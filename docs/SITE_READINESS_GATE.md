# Site readiness gate: live-like telemetry vs staff-entered assumptions

## Why this exists

Some inputs change over time and should come from sensor readings or a timestamped sensor export: wind/PV output, critical electrical load, and usable freshwater inventory. Other inputs are asset facts or planning assumptions, such as reservoir capacity and RO nameplate capacity. CAPEX and annual O&M are commercial inputs that staff must enter from a quotation, engineering estimate, or explicitly labelled assumption.

IslandOS does not currently connect to a deployed sensor network. The readiness gate accepts a staff-prepared JSON snapshot; a future adapter can populate the telemetry section from a sensor gateway/export. Do not describe this as live telemetry integration.

## Run the gate

Start with `config/site_readiness.example.json`, copy it to a local working file, and replace placeholders with verified site values. Keep confidential files out of the public repository.

```bash
python site_readiness.py path/to/site_readiness.json --mode dispatch --json
python site_readiness.py path/to/site_readiness.json --mode economic --json
```

- `dispatch`: blocks if required site, time, telemetry, reservoir, or RO equipment inputs are missing, malformed, physically inconsistent, or telemetry is older than 60 minutes by default.
- `economic`: applies the same gate and additionally blocks unless staff provide RO plant CAPEX, reservoir/storage CAPEX, integration CAPEX, annual O&M, and a traceable source reference.
- Exit code `0`: the requested input-completeness gate passed. Exit code `2`: blocked. A blocked result lists missing or invalid fields.
- Set `--max-telemetry-age-minutes` to a site-approved freshness threshold. Do not loosen it just to make a scenario pass.

## Input ownership

| Input | Expected source | Gate behavior |
|---|---|---|
| Wind, PV, critical load | Sensor reading/export, timestamped | Required; numeric, finite, non-negative |
| Usable reservoir inventory | Level/volume sensor or verified timestamped reading | Required; must not exceed usable capacity |
| Telemetry timestamp + source reference | Sensor clock/export metadata | Required; rejects stale readings and timestamps far in the future |
| Reservoir usable capacity | Asset register / operator-verified site data | Required static parameter |
| RO capacity and specific electricity use | Equipment datasheet / verified test | Required static parameters |
| CAPEX and annual O&M | Staff-entered quote or estimate with source/date | Required only for economic mode |

## Safety and honesty boundary

This is a **readiness gate, not a controller**. It never starts equipment or dispatch, authenticates sensor identity, verifies calibration, validates water quality, checks every electrical/protection interlock, or proves engineering safety. A `READY_FOR_OFFLINE_SCENARIO` result means only that the listed inputs passed this program's completeness and basic plausibility checks. Live control would require a separate, professionally reviewed safety architecture, fail-safe behavior, authorization, and site integration.

CAPEX completeness does not mean CAPEX is accurate. Record currency, tax treatment, quotation date, scope, contingencies, financing, and lifecycle assumptions in the source record before using economics in a competition or investment case. Never invent missing values or silently treat blanks as zero.
