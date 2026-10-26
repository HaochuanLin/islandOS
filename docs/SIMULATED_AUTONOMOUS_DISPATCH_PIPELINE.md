# End-to-end simulated autonomous dispatch pipeline

This workflow connects the existing rolling-horizon dispatcher to the independent fail-closed gate, creating one reproducible path from hourly inputs to audited simulated `ON` / `OFF` / `HOLD` decisions.

## Run it

From the repository root:

```bash
python -m experiments.run_simulated_autonomous_dispatch --hours 24
python -m experiments.run_simulated_autonomous_dispatch --hours 24 --telemetry-invalid
python -m experiments.run_simulated_autonomous_dispatch --hours 24 --interlocks-unhealthy
python -m experiments.run_simulated_autonomous_dispatch --hours 24 --operator-stop
```

The default report is written to `build/simulated-autonomous-dispatch/report.json`. Choose a different `--output` path if you want to preserve an earlier run. To process a user-provided hourly scenario, pass `--input-csv path/to/scenario.csv`; it must follow the schema accepted by `parse_scenario_csv` in `experiments/rolling_horizon_dispatch.py`.

The report preserves each dispatch audit row beside its gate decision and reason code, summarizes ON/OFF/HOLD counts, and explicitly records the dataset status and non-live mode. It also records the input CSV's SHA-256 digest, row count, and first/last timestamps so the exact input bytes can be identified and the synthetic run reproduced. `--max-total-power-kw` is a software-test envelope only; it is not an engineering recommendation or site-approved setting.

## What is integrated

1. Parse timestamp-aligned hourly actual/forecast renewable surplus, actual water demand, cooling demand, and optional forecast water demand.
2. Run the existing rolling-horizon dispatcher with forecast inputs for planning and realized inputs for one-hour execution.
3. Pass each hourly audit row through the deterministic fail-closed gate.
4. Preserve evidence, reason codes, and summary counts in a JSON report.
5. Exercise invalid telemetry, unhealthy interlock status, and operator stop through command-line flags so the fail-closed path can be reproduced.

## Safety and evidence boundary

This is an integration test of software components, not a live autonomous controller. By design, it performs no physical writes, has no hardware connection, and does not verify real sensor authenticity or PLC interlocks. The generated scenario is synthetic. Uploaded CSV is labeled user-supplied and unverified; a file's presence or hash does not prove its measurements are authentic. The simplified dispatch model does not include every plant dynamic, electrical protection, reserve requirement, or site constraint. A successful run is evidence of reproducible software behavior only—not measured forecast skill, equipment feasibility, safety certification, or operational benefit.

Any future field integration must begin with authenticated read-only telemetry and shadow-mode comparison, site-specific reviewed limits, independent interlock enforcement, a tested manual stop/rollback path, operator approval, and an independent engineering and safety review. A language model must not bypass the deterministic gate or issue unrestricted actuator commands.
