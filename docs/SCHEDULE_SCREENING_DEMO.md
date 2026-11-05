# Reproducible Schedule Screening Demo

Run:

```bash
python tools/run_schedule_screening_demo.py --hours 168 --seed 20261105
```

The script creates three transparent RO power-request baselines—off, 50% renewable-surplus-following, and full renewable-surplus-following—and evaluates all three against the same chronological scenario and physical model.

Outputs in `build/schedule-screening/`:

- `schedule_screening.json`: provenance, candidate-generation rules, assumptions, ranking order, and summary metrics.
- `schedule_screening.csv`: compact ranked comparison for spreadsheets and review.

The input scenario is synthetic and repeatable. The ranking is lexicographic, not a weighted multi-objective optimum. Feasibility requires both essential electricity and water demand to be fully served within numerical tolerances. A schedule can therefore rank poorly when water demand is unmet even if its energy cost is low.

This demo does not establish forecast accuracy, real customer savings, equipment suitability, or field validation.
