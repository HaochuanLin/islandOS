# Local demo deployment runbook

Status: **local research/demo deployment only**. This guide does not describe a production or safety-certified deployment.

## Safety and exposure boundary

- The Streamlit application is a research prototype. It has no application-level authentication or role-based access control in this configuration.
- Do not expose the app directly to the public internet, bind it to a public interface, or place it in front of real operational systems. The Compose file intentionally publishes port 8501 on `127.0.0.1` only.
- The Compose demo drops all Linux capabilities, enables `no-new-privileges`, and uses an init process. These are defense-in-depth defaults for the local demo, not a replacement for production isolation or access controls.
- Do not upload confidential, personal, critical-infrastructure, or otherwise restricted site data unless the data owner has approved the environment, retention, access, and handling arrangements.
- No app workflow should be treated as a PLC/actuator command path. Simulation feasibility is not equipment safety approval.
- Use synthetic examples for a first smoke test. Uploaded files are unverified input, not automatically measured or trusted data.

## Prerequisites

- Git and Docker Engine with the Docker Compose plugin, or Python 3.11+ for a non-container local run.
- A checkout of the intended repository revision. Record the Git commit SHA with any result you share.

Check the revision:

```bash
git rev-parse HEAD
```

## Preflight before startup

From the repository root, run the static configuration check before starting the demo:

```bash
python tools/deployment_preflight.py
python tools/deployment_preflight.py --json > deployment-preflight.json
```

The check verifies the pinned base-image digest, non-root container user, loopback-only Compose binding, health-check configuration, retained container SBOM workflow, documented security boundary, and current Git revision. The JSON output is suitable for attaching to a demo record. A failure blocks this local preflight; a pass is **not** production authorization and does not test a running container or validate site data.

## Option A — Docker Compose (recommended for a repeatable local demo)

From the repository root:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 islandos-web
```

The app should be available from the same machine at [http://127.0.0.1:8501](http://127.0.0.1:8501). Do not change the port mapping to `0.0.0.0:8501:8501` on an untrusted network.

Check the Streamlit health endpoint locally:

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5).read().decode())"
```

A healthy HTTP response proves that the web process is responding; it does not validate the simulation, uploaded data, or site readiness.

Stop the demo:

```bash
docker compose down
```

After changing source code, rebuild and restart so the container uses the checked-out revision:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose ps
```

Keep the commit SHA, command output, and any exported reports together when recording a reproducible demonstration.

## Option B — Run with a local Python environment

From the repository root:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and launch the app:

```bash
python -m pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Stop the process with `Ctrl+C`.

## Before sharing a result

1. Record the Git commit SHA and the exact input file(s); retain SHA-256 hashes where applicable.
2. State whether each input is synthetic, public, forecast, manually entered, or measured. Do not infer provenance from a filename.
3. Keep the configuration, units, time zone, timestamp coverage, assumptions, warnings, and exported result together.
4. Report unmet water/cooling demand and constraint violations, not only renewable-energy utilization.
5. Repeat the run when reproducibility matters and compare the outputs; note any differences.
6. Treat all model limitations and data-quality warnings as part of the result, not optional footnotes.

## Production readiness: not yet established

This runbook does not provide the controls needed for a production service. Before any wider deployment, the project owner and qualified reviewers must define and test at least:

- Authentication, authorization, identity lifecycle, and audit logging.
- TLS termination, network segmentation, firewall policy, vulnerability management, and patch cadence.
- Data classification, retention/deletion, backup/restore, incident response, and access to uploaded/exported files.
- Dependency and image pinning, software bill of materials, image scanning, signed release artifacts, and rollback. CI now retains CycloneDX SBOM artifacts for each Python lock and separately generates a CycloneDX SBOM from the built container image; neither artifact signs the image or proves the image is vulnerability-free. See [SECURITY.md](../SECURITY.md) for vulnerability reporting guidance.
- Load limits, availability objectives, monitoring/alerting, support ownership, and recovery procedures.
- Site-specific data permissions, validation, operational sign-off, and a separate safety review for any future integration.

Do not describe the current app as production-ready until these controls have been implemented and independently reviewed. A passing Docker smoke test verifies startup in that test environment only.
