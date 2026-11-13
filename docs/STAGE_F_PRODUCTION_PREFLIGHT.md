# Stage F — production configuration preflight

## Delivered slice

`islandos_core/production_preflight.py` and `islandos_deploy_preflight.py` add a fail-closed configuration-manifest check for future production deployments. It checks declared references and settings for:
- managed PostgreSQL rather than local SQLite;
- HTTPS identity-provider and public application URLs;
- secret-manager, network-policy, backup-key, and metrics-auth references;
- MFA, database TLS, trusted proxy configuration, authenticated metrics, and encrypted off-host backup flags;
- explicit HTTPS origin allowlists and minimum audit retention;
- a mandatory `device_write_enabled=false` boundary.

The report does not echo connection strings or secret values. A passing result is named `configuration_checks_passed`, not “production ready”, and always sets `operational_approval=false`.

## Usage

```bash
python islandos_deploy_preflight.py --config deployment/production.example.json --output build/preflight/report.json
```

Provide a JSON manifest with the required fields. Do not commit live credentials or real infrastructure endpoints.

## What this does not do

This is a configuration contract only. It does not provision PostgreSQL, connect to a secret manager, configure TLS/network policies, verify MFA, create backups, test restore, expose metrics, or connect a site feed. Referenced infrastructure is not contacted or authenticated. Production deployment and field shadow remain blocked until each control is implemented and independently verified.