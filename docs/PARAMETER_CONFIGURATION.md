# IslandOS parameter configuration

IslandOS separates **input data**, **equipment assumptions**, **search ranges**, and **economic data**. The goal is to make uncertain values editable and visible rather than burying them in Python code.

## Current entry points

- Time series: `data/templates/site_hourly_input_template.csv`
- Parameter file: copy `config/site_parameters.example.json` and edit it
- Configuration validator and defaults: `islandos_config.py`
- Site-data optimizer: `experiments/run_nsga2_from_csv.py`

Example command:

```bash
python experiments/run_nsga2_from_csv.py path/to/site_hourly.csv \
  --config config/site_parameters.example.json \
  --source-type measured \
  --output-dir build/site-optimization
```

The example JSON intentionally labels its values as illustrative assumptions. The RO specific energy, reservoir state/capacity, chiller COP/storage, and NSGA-II decision ranges can be edited. Values in `search_space` are candidate values the optimizer may try, not necessarily the actual installed equipment rating. For example, narrow the RO rated-power search to ratings supported by vendor data or the planned equipment.

## Configuration sections

- `metadata`: name, status, and caveats for the configuration.
- `equipment.ro`: RO specific energy, freshwater reservoir capacity/state, dead storage, and backup permission.
- `equipment.ice`: chiller coefficient of performance and thermal-storage capacity/state.
- `search_space`: the discrete decision options explored by NSGA-II.
- `economics`: optional cost inputs. Unknown values should remain `null`.
- `parameter_sources`: a reminder to record provenance for overrides.

Units are embedded in parameter names. Energy intensity is kWh/m³; freshwater is m³; thermal storage is kWh_th; power is kW; COP is dimensionless. This model uses hourly time steps.

## Provenance and uncertainty

For every non-default value used in a real-site study, record at least:
1. value and unit;
2. source type (measured, vendor specification/quote, public source, engineering assumption, or unknown);
3. source name/link and retrieval date;
4. uncertainty/range, if known;
5. responsible person and any transformation applied.

Keep raw data unchanged. Do not call a value “measured” just because it was typed into the JSON file. The current configuration validator checks structure and numerical consistency, not whether a source is genuine.

## Cost fields: honest status

The JSON reserves fields for electricity price, RO/chiller capital and fixed O&M costs, RO variable O&M, analysis period, discount rate, and currency. They are **not yet a lifecycle-cost model**. Supplying these values does not change the NSGA-II objective functions, and the output must not be described as cost-optimal. A cost model needs a documented system boundary, replacement schedules, discounting, capacity-factor assumptions, and explicit treatment of unmet-service penalties before cost can be optimized responsibly.

## Run an equipment sensitivity check

Use the same hourly CSV and base configuration to test whether conclusions change when one uncertain equipment assumption is varied:

```bash
python experiments/parameter_sensitivity.py path/to/site_hourly.csv \
  --config config/site_parameters.example.json \
  --source-type measured \
  --relative-change 0.2 \
  --output build/parameter-sensitivity.json
```

The current experiment compares a baseline with low/high perturbations for RO specific energy, chiller COP, freshwater reservoir capacity, and thermal-storage capacity. It uses a fixed seed and the same optimizer budget for every case, then records Pareto-objective ranges and feasible-candidate counts. Storage-capacity perturbations are clipped so the capacity cannot fall below the configured initial inventory.

This is a deterministic one-factor-at-a-time stress test, **not** probabilistic uncertainty quantification, a confidence interval, or evidence that a tested value is likely. It does not yet model parameter interactions, cost uncertainty, forecast uncertainty, or lifecycle costs. Conclusions remain conditional on the supplied data and simplified physics.

## What validation does and does not mean

The validator rejects non-finite/negative cost values, invalid equipment bounds, invalid COP/specific-energy values, and malformed decision ranges. It does not validate manufacturer claims, plant safety, thermodynamics beyond implemented simplified checks, or whether an assumed value represents a real island. Missing costs are allowed and reported as missing.

## Planned extensions

1. Add source metadata per individual parameter (including a URI/date and confidence range).
2. Implement lifecycle-cost calculations with a transparent boundary and tests.
3. Add sensitivity/scenario analysis for uncertain equipment and economic values.
4. Add a graphical form after the configuration contract stabilizes.
