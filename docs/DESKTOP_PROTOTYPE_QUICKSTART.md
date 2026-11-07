# IslandOS Desktop Prototype Quickstart

## What this is

The optional PySide6 client is the first local desktop workflow shell around the
same UI-independent services used by the Streamlit onboarding experiment. It
currently supports:

- Creating a new local SQLite project after explicit metadata-storage consent.
- Reopening an existing project after verifying its local audit chain.
- Inspecting a CSV or XLSX file in memory.
- Reviewing the import report and task-specific readiness result.
- Saving import metadata and a SHA-256 digest to the local workspace after a
  separate explicit consent.
- Recording only the source filename, hash, metadata, and audit event; it does
  not copy the original uploaded file bytes into SQLite.

It does **not** yet run the energy forecast, microgrid simulation, dispatch
optimizer, or hardware control. It is not a customer-ready installer.

## Run from a clean Python environment

Use Python 3.11 or newer in the current development setup.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-desktop.txt
python -m desktop_app.main
```

The current dependency set includes the repository's existing analysis stack
and optional PySide6 UI. This prototype has not yet been packaged into a
standalone EXE; a clean Windows build and runtime test are still required.

## First-use flow

1. To start fresh, choose a new SQLite workspace file. To continue work, use **Open existing…**, select the database, and enter the project ID.
2. For a new project, enter a project ID, project name, and local operator ID.
3. Explicitly consent to local project metadata storage and create the project.
4. Select a CSV or XLSX file for inspection.
5. Review the quality issues and task-readiness blockers in the result panel.
6. Separately consent before saving import metadata.

For XLSX files, provide the site's IANA timezone when timestamps are naive.
Do not guess UTC or use the computer's local timezone by default.

## Data and safety boundaries

- Use synthetic or appropriately redacted files during development.
- This is a local application, but the current SQLite store is not encrypted.
- Do not store passwords, API keys, VPN credentials, or control-system secrets.
- A valid import is not proof of sensor calibration or site accuracy.
- A readiness result permits only the named offline screening task.
- No command is sent to a PLC, inverter, battery management system, generator,
  or other equipment.
- Never operate equipment solely on the basis of this prototype's output.

## Development rule

The desktop client must call `islandos_core.application`; it must not reimplement
CSV/XLSX parsing, data-quality gates, project persistence, or audit rules.
Keep PySide6 optional so the shared core and Streamlit workflows remain usable
without installing desktop UI dependencies.

## Build a Windows prototype executable

A GitHub Actions workflow is available at
`.github/workflows/windows-desktop-prototype.yml`. Run it manually from the
Actions tab, or push a change to the desktop/core paths on the configured
branches. A successful run uploads the onedir prototype as the
`IslandOS-Windows-Desktop-Prototype` artifact for 14 days.

The workflow verifies that PyInstaller creates
`dist/IslandOS/IslandOS.exe`. It does not yet perform a full interactive GUI
acceptance test, create a signed installer, configure auto-updates, or certify
the application for customer deployment. Treat the artifact as an engineering
prototype only.
