# Reproducibility and evidence

This repository is a research prototype. The commands and artifacts below make experiments inspectable; they do not establish that a model transfers to an island site or is safe to control equipment.

## Run the local regression suite

Use Python 3.11, matching the main CI runner:

```bash
python -m pip install --upgrade "pip==26.2.2"
python -m pip install -r requirements-ci.lock
python -m pip check
python -m compileall -q .
python -m pytest -q
```

The CI workflow installs `requirements-ci.lock`, an exact version lock captured from a successful Python 3.11 run, and checks that every declared runtime/ML requirement is covered by that lock. `requirements-ml.lock` pins the smaller optional forecasting dependency set and is used by the measured-data workflow. The workflow records commit SHA, runner platform, Python version, and resolved installed distributions in an `environment.json` artifact. The CI and runtime lockfiles pin package versions but do not include package hashes. The Dockerfile installs `requirements-runtime.lock` (not the range-based `requirements.txt`) and runs `pip check`; the base image is still tagged `python:3.11-slim` rather than pinned by immutable digest, and image signing/SBOM generation are not configured. The dependency-audit workflow scans the exact Python locks. Its first run caught vulnerable `setuptools==79.0.1` (PYSEC-2026-3447); the CI lock now pins `setuptools==83.0.0`, while the runtime lock pins `setuptools==84.1.0`. These locks have separate dependency sets and must each be audited.

## Reproduce the public SOWEKI demand baseline

On pushes, relevant pull requests, and a weekly schedule, the public-data workflow evaluates all 11 SOWEKI series from the [Zenodo record](https://zenodo.org/records/19627517) (CC BY 4.0) in parallel. Manual dispatch still lets you select one series. Each job audits timestamp ordering, prepares hourly data without interpolation, and evaluates chronological holdout forecast baselines.

Local preparation and evaluation:

```bash
python experiments/prepare_soweki_water_demand.py \
  build/public-data/raw/soweki_source.csv \
  --output build/public-data/soweki_hourly.csv \
  --report build/public-data/preparation.json

python experiments/water_demand_forecast.py \
  build/public-data/soweki_hourly.csv \
  --output build/public-data/forecast_report.json

python -m pip install "scikit-learn>=1.4"
python experiments/compare_water_demand_models.py \
  build/public-data/soweki_hourly.csv \
  --output build/public-data/model_comparison.json
```

The first command expects you to supply the downloaded source CSV at the shown path. To download a series directly, use the adapter's `--download --dataset-id N` options and choose a series from 1 through 11.

The preparation report includes:

- `source_file_sha256`: SHA-256 of the exact input CSV bytes.
- `prepared_hourly_csv_sha256`: SHA-256 of the produced hourly CSV bytes.
- Source row counts, duplicate handling, excluded invalid values, time span, missing-data policy, and limitations.

The public-data CI independently recomputes both hashes and fails on a mismatch. It also compares a scikit-learn gradient-boosting candidate with persistence, previous-day, and previous-week seasonal baselines on the same chronological holdout. The model report records the prepared CSV hash and scikit-learn version. It also retrains at up to three expanding-window boundaries: every fold uses only targets before its test window and reports metrics against the same naive baselines. Each series artifact retains the raw CSV, prepared hourly CSV, preparation report, baseline forecast report, ML comparison report, and measured-data summary for 90 days. A separate aggregation job publishes per-series metrics, missing-series status, and mean/median MAE reduction for both the primary holdout and the expanding-window evaluation. Use the hashes to confirm that files match the reported experiment; a hash does not prove the source measurements are accurate.

## What the results mean

- Forecast metrics are evaluated on chronological holdout data; the rolling-origin baseline uses only earlier observations for each target. The ML candidate is a small gradient-boosting model, not deep learning or online learning, and it must earn its place by outperforming simple baselines on measured data.
- Gaussian demand/error behavior is diagnosed rather than assumed. Prediction-interval coverage is empirical and not guaranteed.
- SOWEKI is measured demand from rural German reservoir outflows, not island or Nan'ao measurements. A result on this dataset does not establish transfer to another location, season, or operating regime.
- Synthetic simulation, public-data backtests, and successful CI runs are not field validation. Real deployment requires qualified site review, independent measurement checks, shadow-mode evaluation, fail-safe behavior, human authorization, and rollback procedures.

## Evidence links

- [Main regression workflow](https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml)
- [Public measured-data backtest workflow](https://github.com/HaochuanLin/islandOS/actions/workflows/public-data-backtest.yml)
- [Successful 11-series matrix, expanding-window backtests, and aggregate report](https://github.com/HaochuanLin/islandOS/actions/runs/39987177812)
- [Earlier single-series measured-data run with SHA-256 checks](https://github.com/HaochuanLin/islandOS/actions/runs/39984656770)
- [Maturity assessment and remaining gaps](MATURITY_ASSESSMENT.md)


## Docker runtime lock

The Docker image installs `requirements-runtime.lock`, a pinned Python 3.11 runtime environment derived from the passing CI environment. It avoids resolving the floating version ranges in `requirements.txt` at image-build time and excludes the direct pytest runner and optional scikit-learn forecasting package. The lock intentionally keeps the conservative runtime dependency closure. The dependency-audit workflow checks this lock as well. Exact package pins improve repeatability but do not guarantee bit-for-bit identical images; base-image digests and wheel hashes remain separate hardening opportunities.
