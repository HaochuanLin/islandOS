# Stage 8 — deployment and onboarding

## Delivered local deployment workflow

A cross-platform Python CLI wraps the existing Docker Compose research/demo deployment:

```bash
python tools/islandos_local.py doctor
python tools/islandos_local.py up
python tools/islandos_local.py status
python tools/islandos_local.py down
```

The `up` command:
1. Runs the static deployment preflight and blocks startup if it fails.
2. Validates the Compose configuration.
3. Builds the image unless `--no-build` is supplied.
4. Starts the existing Compose service.
5. Waits for the local Streamlit health endpoint.

The existing Compose port is bound to `127.0.0.1:8501`; the helper does not open firewall ports or change the bind address.

## Explicit limits

This is a repeatable local demo installer/operator helper, not a production installer. It does not deploy the React customer console with its API, create a managed PostgreSQL database, configure SSO/MFA, provision a secret manager, create backups, set up TLS, or install a vendor device driver. Do not expose the loopback reference services to a network. Production deployment remains blocked by the production preflight until real infrastructure and security controls are configured and independently reviewed.

## Verification

Unit tests mock the subprocess and health endpoint. CI validates Python behavior; a target machine still requires Docker Compose and an operator-run smoke test.
