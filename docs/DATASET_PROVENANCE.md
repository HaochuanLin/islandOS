# Dataset provenance validation

IslandOS includes a small, offline validator for provenance metadata used in
experiments. It validates the shape and internal consistency of a provenance
record; it does **not** verify that a source is accurate, that a licence permits
a particular use, or that a dataset represents a target island.

## Validate metadata

Create a JSON object with these fields:

- `dataset_id`, `source_name`, `source_url` (absolute HTTPS URL)
- `retrieved_at`, `time_start`, `time_end` (ISO-8601 timestamps with offsets)
- `timezone`, `frequency`
- `variables`: a non-empty list of objects containing `name`, `unit`, and `meaning`
- `license`, `data_status`, `source_version`

Allowed `data_status` labels are `measured`, `public_reanalysis`, `modeled`,
and `synthetic`. Choose the label that accurately describes the data; public
reanalysis is not the same as an in-situ site measurement.

Run:

```bash
python experiments/validate_dataset_provenance.py provenance.json
```

The command prints normalized JSON to standard output. To save it:

```bash
python experiments/validate_dataset_provenance.py provenance.json --output build/provenance.normalized.json
```

## Bind the record to a local file

To compute the SHA-256 digest of the exact artifact bytes and include it in the
normalized record:

```bash
python experiments/validate_dataset_provenance.py provenance.json --artifact data/hourly.csv --output build/provenance.normalized.json
```

If the metadata already contains a `sha256` value, the command verifies it
matches the supplied file and fails closed if it does not. Keep the original
source record and the normalized output with experiment results when auditability
matters.

Invalid input returns a non-zero exit status and writes a concise diagnostic to
standard error, so the command can be used in CI or scripts.

## Important limits

- A valid HTTPS URL is a syntax check, not proof that the resource exists or is trustworthy.
- The validator cannot determine whether a licence statement is correct or whether redistribution is allowed.
- A matching hash proves byte identity only; it does not prove the data is accurate.
- Timestamps and variable units must be checked against the source documentation.
- Site suitability, forecast accuracy, engineering feasibility, and operational
  safety require separate evidence and cannot be inferred from provenance metadata.
