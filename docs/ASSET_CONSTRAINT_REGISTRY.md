# IslandOS Asset and Constraint Registry

## Purpose

The asset registry keeps three different kinds of equipment information
separate: vendor nameplate ratings, the configuration actually installed at a
site, and observed operating behavior. Operating constraints are versioned
records with source references and explicit confirmation state.

## Constraint severity

- **Hard:** a boundary that a candidate recommendation must never violate.
- **Operational:** a site operating rule that applies by default.
- **Soft:** a preference that may be traded off and explained.

The first Streamlit form captures required hard constraints for common asset
types. The core schema supports all three severity levels.

## Required minimum constraints for offline screening

| Asset type | Required confirmed hard constraints |
|---|---|
| PV | Maximum usable power |
| Wind | Maximum usable power |
| Battery | Maximum charge power, maximum discharge power, minimum SOC, maximum SOC |
| Diesel generator | Maximum power, minimum stable power |
| Grid connection | Import limit |
| Flexible load | Maximum power, minimum power |
| Generic | No generic default; add asset-specific constraints before use |

The core also requires confirmed installed configuration fields: configured
power for all named asset types, and usable energy capacity for batteries.
These requirements intentionally distinguish a vendor datasheet from the
site's installed configuration.

## Provenance requirements

Every parameter and constraint must include:
- numeric value and unit;
- source type (measured, customer-provided, vendor specification, inferred,
  or synthetic);
- traceable source reference;
- explicit confirmation state.

Inferred values are not automatically treated as confirmed. The Streamlit
experiment requires a source reference and makes the operator confirm entered
hard limits. A missing or unconfirmed hard limit blocks asset screening.

## Validation behavior

- Values must be finite numeric values.
- Known parameter names have canonical units.
- Min, max, and range operators must have the appropriate bounds.
- Range lower bound cannot exceed upper bound.
- Required hard constraints must use the correct direction (for example,
  maximum charge power is a max constraint), and exactly one confirmed hard
  constraint must exist for each required parameter; ambiguous duplicates block screening.
- Nameplate and installed power/energy ratings must use canonical units and
  be positive; SOC bounds must remain within 0–100%; known power limits cannot be negative.
- Battery minimum SOC must be below maximum SOC.
- Duplicate constraint IDs are rejected.
- An unavailable asset cannot be screened.

## Run the experiment

```bash
streamlit run pages/4_Asset_Constraint_Lab.py
```

The Streamlit lab currently keeps its interactive form records in session state and can export a JSON registry. The shared local application core also supports consent-based, project-scoped SQLite asset persistence through `register_project_asset` and `list_project_assets`. Each save appends an immutable version with a content hash, readiness snapshot, and audit event; the latest version can be loaded and the full version history inspected. The current Streamlit form is not wired directly to local persistence; export its JSON registry and import it from the optional Windows desktop shell after opening a local project. The desktop shell stores each imported asset as an immutable project-scoped version and can display the latest saved registry and readiness blockers. Neither path connects to equipment, verifies source documents, certifies equipment settings, or issues control commands.

## Current limitations

The first form captures the minimum hard constraints for common asset types.
It does not yet provide a complete asset lifecycle, maintenance calendar,
vendor catalogue, automatic datasheet extraction, or live device discovery.
Electrical topology is currently a separate structural validation service; it
does not perform power flow or electrical safety analysis.
