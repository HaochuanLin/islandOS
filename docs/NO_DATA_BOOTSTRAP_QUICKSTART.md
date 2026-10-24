# No-data site bootstrap quickstart

This workflow lets a user create a named, editable configuration and run a synthetic demonstration without first collecting site data. It is a software onboarding path, not field validation.

## 1. Create a local configuration

From the repository root:

```bash
python tools/init_site_config.py --site-name "Demo island" --output config/demo-island.json
python -c "from islandos_config import load_config; print(load_config('config/demo-island.json')['metadata'])"
```

The command refuses to overwrite an existing file unless `--force` is explicitly passed. It starts from the checked-in example configuration, names the study, and marks the values as illustrative defaults.

## 2. Run the no-data simulation

```bash
python tools/run_synthetic_site_demo.py --hours 168 --seed 20261023
```

The command writes the synthetic hourly input, a provenance manifest, a strategy summary, a timestep audit, and a JSON report to `build/synthetic-site-demo/`. The demo command uses its explicit command-line equipment assumptions; it does not silently read the generated site configuration. This is intentional until a single shared config contract is wired into all simulation entry points.

## 3. Replace assumptions before site-specific interpretation

Edit the local JSON file and record the source, date, units, and uncertainty for relevant values. Generate a CSV from an approved source and run:

```bash
python tools/validate_site_csv.py path/to/site_hourly.csv --json
```

Do not label assumed values as measured. A structurally valid configuration or CSV does not authenticate data provenance, certify physics, or approve plant operation. Keep the raw source data unchanged and treat outputs as planning results until they are calibrated and reviewed for the target site.
