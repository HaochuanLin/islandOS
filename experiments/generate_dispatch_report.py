"""Generate reproducible charts and tabular outputs for the synthetic dispatch experiment.

Run from the repository root:
    python experiments/generate_dispatch_report.py --output-dir build/dispatch-report

Results are synthetic scenario results, not measured island performance.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from html import escape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_dispatch_policies import run_comparison

METRICS = (
    ("remaining_surplus_kwh", "Remaining surplus", "kWh"),
    ("water_unmet_m3", "Unmet water demand", "m³"),
    ("cooling_unmet_kwh_th", "Unmet cooling demand", "kWhₜₕ"),
)
POLICIES = ("ro_only", "ice_only", "ro_first", "ice_first")


def _svg_chart(rows: list[dict]) -> str:
    scenarios = list(dict.fromkeys(row["scenario"] for row in rows))
    width, height = 1100, 790
    left, right = 220, 1060
    panel_h = 205
    top = 72
    colors = {
        "ro_only": "#2563eb",
        "ice_only": "#0891b2",
        "ro_first": "#16a34a",
        "ice_first": "#d97706",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.subtitle{font-size:13px;fill:#475569}.metric{font-size:17px;font-weight:700}.tick{font-size:11px;fill:#64748b}.label{font-size:12px}.legend{font-size:12px}</style>',
        '<text x="40" y="36" class="title">IslandOS — synthetic dispatch policy comparison</text>',
        '<text x="40" y="56" class="subtitle">12 runs · 3 synthetic scenarios · 4 policies · 1-hour steps · not field measurements</text>',
    ]
    for index, (key, title, unit) in enumerate(METRICS):
        y0 = top + index * (panel_h + 25)
        max_value = max((float(r[key]) for r in rows), default=0.0)
        scale_max = max(max_value * 1.12, 1.0)
        plot_top, plot_bottom = y0 + 35, y0 + 150
        plot_h = plot_bottom - plot_top
        parts.append(f'<text x="40" y="{y0+16}" class="metric">{escape(title)} ({escape(unit)})</text>')
        for tick_i in range(5):
            value = scale_max * tick_i / 4
            y = plot_bottom - plot_h * tick_i / 4
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#e2e8f0"/>')
            parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" class="tick">{value:.1f}</text>')
        group_w = (right - left) / len(scenarios)
        bar_w, gap = 12, 4
        total_w = len(POLICIES) * bar_w + (len(POLICIES) - 1) * gap
        for si, scenario in enumerate(scenarios):
            gx = left + si * group_w + (group_w - total_w) / 2
            for pi, policy in enumerate(POLICIES):
                row = next(r for r in rows if r["scenario"] == scenario and r["policy"] == policy)
                value = max(0.0, float(row[key]))
                bar_h = value / scale_max * plot_h
                x = gx + pi * (bar_w + gap)
                y = plot_bottom - bar_h
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{bar_h:.1f}" rx="2" fill="{colors[policy]}"/>')
            cx = left + si * group_w + group_w / 2
            parts.append(f'<text x="{cx:.1f}" y="{plot_bottom+20}" text-anchor="middle" class="label">{escape(scenario.replace("_", " "))}</text>')
    legend_y, legend_x = height - 17, 260
    for policy in POLICIES:
        parts.append(f'<rect x="{legend_x}" y="{legend_y-10}" width="12" height="12" rx="2" fill="{colors[policy]}"/>')
        parts.append(f'<text x="{legend_x+18}" y="{legend_y}" class="legend">{escape(policy)}</text>')
        legend_x += 155
    parts.append("</svg>")
    return "\n".join(parts)


def generate_report(output_dir: str | Path) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = run_comparison()
    payload = {
        "project": "IslandOS",
        "experiment": "synthetic_dispatch_policy_comparison",
        "data_status": "synthetic illustrative scenarios; not field measurements",
        "time_step_hours": 1.0,
        "scenario_count": len({r["scenario"] for r in rows}),
        "policy_count": len({r["policy"] for r in rows}),
        "run_count": len(rows),
        "units": {"energy": "kWh", "water": "m3", "cooling": "kWh_th", "time_step": "hour"},
        "metrics": list(dict.fromkeys(key for row in rows for key in row)),
        "rows": rows,
        "limitations": [
            "Scenario profiles are synthetic and do not represent a named island.",
            "Component models are simplified and not site-calibrated.",
            "Priority-order results are scenario-specific; no universal winner is claimed.",
            "Remaining surplus alone does not measure reliability or overall system value.",
        ],
    }
    (out / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (out / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "dispatch_comparison.svg").write_text(_svg_chart(rows), encoding="utf-8")
    lines = [
        "# IslandOS synthetic dispatch experiment",
        "",
        "> **Data status:** synthetic illustrative scenarios, not field measurements. Do not cite these values as real-island performance.",
        "",
        f"- Scenarios: {payload['scenario_count']}",
        f"- Policies per scenario: {payload['policy_count']}",
        f"- Total policy runs: {payload['run_count']}",
        "- Time step: 1 hour",
        "- Energy: kWh; freshwater: m³; cooling service: kWhₜₕ",
        "",
        "## Results chart",
        "",
        "![Grouped policy comparison](dispatch_comparison.svg)",
        "",
        "## Full results",
        "",
        "| Scenario | Policy | Remaining surplus (kWh) | Water unmet (m³) | Cooling unmet (kWhₜₕ) | Constraint violations (h) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario']} | {row['policy']} | {row['remaining_surplus_kwh']:.3f} | "
            f"{row['water_unmet_m3']:.3f} | {row['cooling_unmet_kwh_th']:.3f} | "
            f"{row['constraint_violation_hours']} |"
        )
    lines.extend([
        "",
        "## Interpretation limits",
        "",
        *[f"- {item}" for item in payload["limitations"]],
        "",
        "## Reproduce",
        "",
        "    python experiments/generate_dispatch_report.py --output-dir build/dispatch-report",
        "",
        "Generated from experiments/compare_dispatch_policies.py. Power-budget accounting checks run in the simulator before results are returned.",
        "",
    ])
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "output_dir": str(out),
        "run_count": len(rows),
        "scenario_count": payload["scenario_count"],
        "policy_count": payload["policy_count"],
        "files": ["REPORT.md", "results.csv", "results.json", "dispatch_comparison.svg"],
        "data_status": payload["data_status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="build/dispatch-report")
    args = parser.parse_args()
    print(json.dumps(generate_report(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
