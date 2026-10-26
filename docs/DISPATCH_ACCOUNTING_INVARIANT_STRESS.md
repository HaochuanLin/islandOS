# Seeded dispatch accounting invariant suite

This suite runs the same generated synthetic scenarios through the rolling-horizon dispatcher and all four benchmark policies, then checks per-hour accounting and bounds. It is intended to catch software regressions that a policy score alone can hide.

## Run

```bash
python -m experiments.run_dispatch_invariant_stress_suite --hours 24 --cases 12 --seed 20261026
```

The command writes `build/dispatch-invariant-stress/report.json`. The default is 13 paired synthetic cases (baseline plus 12 seeded variants), four policies per case, and 24 hours per run.

## Invariants checked

- Total RO plus chiller electrical power never exceeds realized surplus.
- Water inventory conservation: previous inventory + produced water − served water − spill = next inventory.
- Cold-storage conservation: previous inventory + produced cooling − served cooling − spill = next inventory.
- Water and cold inventories stay within configured bounds.
- Served water/cooling never exceeds realized demand.
- Water production matches RO power and specific energy; cooling production matches chiller power and COP.
- Audited numeric values remain finite.

A nonzero simulated equipment-constraint-violation count is reported separately; the accounting suite does not hide it or reinterpret it as proof of safety. The report includes per-policy summaries, each failed invariant if any, and a deterministic SHA-256 digest. The CLI exits nonzero if any invariant fails.

## Limits

Inputs are generated synthetic profiles and seeded scaling transforms, not a measured-site distribution. Passing means only that these software accounting invariants held in the tested scenarios. The suite does not establish plant fidelity, equipment feasibility, forecast accuracy, site safety, or operational benefit. It must not be used to authorize live control.
