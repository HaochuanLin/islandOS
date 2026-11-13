# Stage F — shadow-mode and deployment-readiness foundation

## Delivered software slice

`islandos_sensors/contract.py` rejects every future-dated sample and provides batch-level duplicate-identity quarantine. `islandos_core/shadow_mode.py` adds a vendor-neutral, read-only comparison between a stored recommendation and later observed telemetry. `islandos_shadow.py` provides an offline JSON replay CLI for recorded recommendation/observation pairs. It checks recommendation/observation identity, timestamp validity and strict freshness (any future-dated observation is blocked), signal coverage, unit consistency, finite values, and per-signal tolerances declared from an approved asset/sensor specification.

Each comparison produces an auditable report with a SHA-256 digest and one of three states:
- `within_tolerance`: all compared signals are within their declared tolerances.
- `deviation`: valid, fresh, unit-aligned observations differ beyond at least one tolerance; operator review is required.
- `blocked`: required evidence is missing, stale, future-dated, malformed, non-finite, or unit-inconsistent.

All outcomes explicitly set `device_write_authorized=false` and `command_generated=false`. A deviation is never auto-corrected. This module is a shadow-comparison primitive; it does not subscribe to a device, schedule jobs, page operators, or establish a field trial.

## Offline replay

Run a recorded comparison without connecting to a device:

```bash
python islandos_shadow.py \
  --recommendation examples/recommendation.json \
  --observation examples/observation.json \
  --evaluated-at-utc 2026-11-13T10:05:00Z \
  --max-age-seconds 300 \
  --output build/shadow/report.json
```

Exit codes: 0 = within tolerance, 1 = valid observation with deviation, 2 = blocked evidence or invalid input. The JSON report includes the no-write invariants and audit digest. Do not treat a zero exit code as operational approval.

## Existing deployment foundations

- Local Docker Compose deployment is loopback-bound, read-only filesystem, dropped Linux capabilities, no-new-privileges, resource-limited, and has bounded container logs.
- The local service API uses tenant-scoped SQLite, opaque expiring bearer sessions, and a loopback-only listener.
- Workspace backup/restore has SQLite integrity and audit-chain verification.
- Telemetry gateway validates timestamps (future timestamps rejected by default), freshness, units, required fields, and source quality; it is read-only and loopback-only. The normalized sensor contract also supports batch duplicate quarantine.
- CI runs unit/integration tests, dependency audit, Windows gateway packaging, container health smoke, and scenario validation.

## Production deployment gates — still open

| Gate | Evidence required before a real pilot | Current status |
|---|---|---|
| Managed database | Selected database, migrations, restore drill, access policy, connection security | Not implemented; local SQLite reference only |
| Secrets and identity | Secret manager, MFA/SSO or approved identity provider, credential rotation, session revocation | Not implemented |
| Transport and network | TLS termination, network segmentation, device identity, firewall rules, ingress/egress review | Not implemented for production |
| Device protocol adapters | Site-specific read-only Modbus/MQTT/vendor connector, point map, unit validation, failure behavior | Contract and simulator/replay only |
| Monitoring and response | Metrics, structured logs, alert routing, retention, incident runbook, owner/on-call assignment | Partial local health/logging only |
| Backup and recovery | Encrypted off-host backups, retention, restore drill, RPO/RTO approval | Local workspace backup primitive only |
| Shadow trial | Site-owned read-only feed, time alignment, drift review, operator comparison, stop rules | Comparison primitive only; no site feed |
| Pilot acceptance | Named data/site/operations/safety/security reviewers and signed owner thresholds | Template only; no approvals |

## Mandatory no-go rules

- No external network exposure of the local reference API or gateway.
- No real customer/critical-infrastructure data until data rights, privacy, security, and retention are approved.
- No device write, setpoint dispatch, automatic correction, or control-loop integration.
- No shadow pilot until the site owner approves the data feed and an independent operator review process.
- No pilot acceptance until measured baseline, chronological holdout, hard-constraint criteria, stop-work rules, and responsible signatories are recorded.

## Validation

`tests/test_shadow_mode.py` checks within-tolerance comparison, deviations, stale/missing/future telemetry, unit mismatch, non-finite values, audit digest generation, and the invariant that no command is generated or authorized. `tests/test_shadow_cli.py` verifies replay report output and distinct exit codes. These are software tests, not hardware-in-the-loop or site-acceptance evidence.