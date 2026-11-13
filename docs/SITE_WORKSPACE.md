# Local site workspace and portable project packages

## Purpose

The site workspace adds a local-first project layer around the existing CSV/XLSX
inspection, asset model, SQLite metadata store, run manifests and audit chain.
It is intended for engineering evaluation on a trusted workstation, not as a
public customer data room or production multi-user service.

## Enable the local workspace

Set these environment variables before launching Streamlit:

- `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1` — explicitly enables local persistence.
- `ISLANDOS_WORKSPACE_DB=.islandos/workspace.sqlite3` — SQLite workspace path.
- `ISLANDOS_WORKSPACE_ID=local-islandos-workspace` — stable workspace identity.
- `ISLANDOS_SOURCE_STORAGE_DIR=.islandos/source_files` — optional original-file archive.
- `ISLANDOS_LOCAL_ACTOR_ID=local_operator` — local audit actor label.

Keep the database and source directory in an OS-approved user-data location
with appropriate filesystem permissions. Do not commit them to Git. Do not
point the public hosted Streamlit demo at a customer database or customer
source-file directory.

## Project workflow

1. Open **Data onboarding & workspace** and upload a CSV or XLSX file.
2. Review the detected columns, units, timestamps, missing values, duplicates,
   quality findings and task-readiness gates.
3. Register import metadata to an existing project or create a new project.
   Metadata storage requires explicit consent.
4. Original CSV/XLSX bytes are not retained by default. A separate opt-in
   stores the exact original file locally only after its SHA-256 digest matches
   the registered import metadata.
5. Open **Site workspace** to add a versioned site profile, record equipment
   assets and their provenance/constraints, and export or import a project ZIP.

## Site profiles and assets

Site profiles are append-only versions and validate IANA time zones and
three-letter reporting currency codes. Asset records preserve vendor/nameplate,
installed and observed values separately. Every parameter and hard operating
constraint must include a source reference. Readiness is a completeness gate
for offline screening; it is not equipment certification or authorization for
control.

## Portable project package

A project ZIP contains a JSON snapshot of project metadata, site profile
versions, asset versions, import metadata, run manifests and project audit
events. If original source files were separately retained and the exporter is
configured to include them, the files are included under opaque artifact IDs.

The package has a SHA-256 manifest for every member. Import validates paths,
member counts, expanded size, file sizes and hashes before writing a new
project. Import never overwrites the active project. The source workspace's
audit events are preserved as embedded evidence; the destination workspace
creates a new local import event rather than claiming the source chain is part
of the destination chain.

## Data protection and limitations

- Source retention is opt-in, local-only, and limited to 20 MiB per CSV/XLSX.
- The package is not encrypted. Use an approved encrypted disk or transfer
  channel when required by the data owner.
- There is no retention scheduler, secure deletion workflow, cloud sync,
  managed multi-user database or production access-control layer.
- File hashes prove byte consistency, not source authenticity or sensor
  calibration.
- A valid import does not establish that the data is fit for every prediction
  or optimization task.
- The public hosted demo has no customer authentication and must not be used
  for confidential customer telemetry.
