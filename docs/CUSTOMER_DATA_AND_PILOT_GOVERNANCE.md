# IslandOS Customer Data and Pilot Governance Checklist

**Status:** Internal product-design checklist; not a customer contract or legal advice.

This checklist is intended to prevent misunderstandings when IslandOS moves
from a synthetic demonstration to a supervised customer evaluation. It must be
reviewed with qualified legal, cybersecurity, and site-engineering personnel
before a real pilot.

## 1. Do not accept data before confirming authority and purpose

Before receiving a file or connecting to a source, record:

- The customer organization and site covered by the evaluation.
- The person providing the data and their authority to share it.
- The customer data owner and the technical contact responsible for the source.
- The specific purpose of processing (for example, offline forecast evaluation
  or dispatch-policy comparison).
- The approved data categories and date range.
- Whether data contains personal information, security-sensitive details,
  critical-infrastructure topology, credentials, or commercially confidential
  information.
- Whether an NDA, data-processing agreement, security review, or procurement
  approval is required.
- The approved processing location: customer workstation, approved customer
  environment, or explicitly approved hosted environment.
- Whether any subcontractor or third-party service can access the data.

**Default rule:** do not upload confidential site telemetry to the public
Streamlit demo. Use synthetic or redacted data there. The hosted demo is not a
customer data room.

## 2. Minimize collection

Request the smallest dataset that can answer the agreed question.

Preferred order:

1. Read-only export from an existing monitoring system.
2. Existing CSV/XLSX reports supplied by the customer.
3. A limited set of manually entered decision-critical values.
4. A new sensor or connector only when the customer approves the scope.

Do not ask for passwords, API secrets, VPN credentials, remote desktop access,
or control-system write credentials in a data-import form. A future connector
must use a separate credential-management and security process.

Do not collect personal information unless it is necessary, authorized, and
covered by an approved data-processing arrangement. Avoid names, phone numbers,
employee schedules, access logs, and unrelated records.

## 3. Record data provenance and quality

For each dataset, capture:

- Source system, export name, site, owner/contact, and source classification.
- Original file hash and ingestion time.
- Date range, timezone, sampling interval, and timestamp convention.
- Signal name, meaning, source unit, canonical unit, and conversion.
- Whether values are measured, calculated, forecast, inferred, or synthetic.
- Sensor/equipment tag and location where available.
- Missing values, duplicates, irregular intervals, outliers, resets, and
  known data gaps.
- Calibration status/date and known sensor faults, if the customer can provide
  them.
- Known maintenance, outages, curtailment, abnormal operation, and manual
  overrides during the dataset period.
- License/permission and restrictions on reuse.

A syntactically valid file is not proof of accurate measurements. A customer
confirmation is recorded as an assertion, not an independent calibration.

## 4. Confirm the physical system before optimization screening

Keep these distinct:

- Vendor nameplate rating.
- Installed and configured rating at this site.
- Observed operating envelope supported by measurements.
- Hard limits that must never be violated.
- Operational rules that apply by default.
- Soft preferences that may be traded off.

For relevant equipment, ask for the following only when applicable:

### Electrical supply and grid
- Import/export limits and interconnection rules.
- Voltage/frequency limits, phase, power factor, and protection settings if
  they affect the model.
- Tariff periods, demand charges, export compensation, and tariff validity.
- Grid outage history and backup-supply transfer assumptions.

### PV and wind
- Installed capacity, inverter/turbine limits, derating, curtailment rules,
  availability, and known shutdown conditions.
- Whether values are AC-side or DC-side measurements.

### Battery
- Usable energy capacity, maximum charge/discharge power, SOC min/max,
  efficiency, reserve policy, degradation limits, temperature limits, and
  warranty restrictions.
- Confirm whether the SOC signal is measured, estimated, or BMS-reported.

### Diesel generator
- Rated and minimum stable power, ramp limits, start/stop constraints,
  minimum run/off time, fuel curve, fuel price, maintenance state, and reserve
  requirements.

### Flexible loads and critical services
- Essential versus flexible demand classification.
- Load-shedding priorities and prohibited interruptions.
- Minimum/maximum operating power, run duration, start/stop frequency, ramp
  rate, process constraints, and required service inventory.
- Operator-approved emergency rules.

Unknown hard limits block the relevant optimization workflow. They must not be
replaced by optimistic defaults. IslandOS screening is not a substitute for
manufacturer instructions, protection studies, or site engineering approval.

## 5. Customer confirmations and responsibility boundaries

Before a recommendation is used in a customer review, obtain written
confirmation from an appropriately authorized customer representative that:

- The site identity, asset inventory, and installed configuration are correct
  to the best of their knowledge.
- The data source, units, timestamps, timezone, and operating period are
  understood.
- The listed hard constraints and critical-load policies are approved by the
  customer's designated engineering authority.
- Known data gaps and abnormal operating periods have been disclosed.
- The customer understands which values are measured, inferred, synthetic, or
  supplied by a vendor.
- The customer understands that IslandOS is an offline decision-support
  prototype and does not issue control commands.
- No operational change will be made solely because of a prototype output;
  existing operating procedures and authorized engineering review take
  precedence.

A checkbox in the software is not a substitute for identifying the authorized
approver or documenting the approval scope.

## 6. Define the pilot before running it

Each pilot should have a short written scope containing:

- Site and assets included/excluded.
- Questions to be answered and decisions explicitly out of scope.
- Data sources and approved processing environment.
- Baseline period and candidate evaluation period.
- Scenario set, stress cases, and known limitations.
- KPIs and calculation definitions (for example, energy cost, unmet critical
  load, renewable curtailment, asset utilization, water/service shortfall).
- Required customer inputs and approval checkpoints.
- Deliverables, review dates, fees if any, and acceptance criteria.
- Named customer and IslandOS contacts.
- Change-control process if data, equipment, constraints, or scope changes.

Never claim savings, ROI, reliability improvement, or avoided CAPEX until a
customer-approved baseline and evaluation method support the claim. Report
simulated outcomes separately from measured outcomes.

## 7. Make every result explainable and reproducible

For each analysis, preserve:

- Original input artifact hashes and source labels.
- Normalized mappings, units, timezone, quality issues, and excluded periods.
- Site configuration and constraint snapshot.
- Forecast/simulation/optimization model versions and parameters.
- Random seed where relevant.
- Software version and execution timestamp.
- Outputs, warnings, assumptions, and unresolved blockers.
- Human reviewer, operator overrides, reasons, and source references.
- Customer approval or rejection of the recommendation, where applicable.

Never overwrite an old run when a customer corrects data or a constraint.
Create a new version and explain what changed and why. If a result is disputed,
replay the original manifest first, then create a corrected run with the
customer's confirmed change.

## 8. Handle overrides and disputes

For every manual override, record:

- Field and asset affected.
- Previous value and proposed value.
- Reason for the change.
- Source document or evidence.
- Proposing person and timestamp.
- Independent reviewer and review outcome, when required.
- Whether the value is pending, approved, or rejected.

An audit record is not proof of a person's authority. The pilot must define
who is allowed to approve engineering constraints. A reviewer should not
approve their own proposal. Disputed values remain unresolved until the
designated customer authority responds.

When a result is challenged:

1. Freeze the disputed run's manifest and outputs.
2. Confirm which source file and configuration version were used.
3. Reproduce the result with the same software/model version and seed.
4. Identify whether the disagreement is caused by data, assumptions, model
   behavior, or interpretation.
5. Record the customer's correction as a new version.
6. Issue a new run and preserve both records.

## 9. Retention, export, deletion, and incident handling

Before collecting customer data, agree:

- What is retained: raw files, normalized data, metadata, reports, manifests,
  audit events, and backups.
- Where it is stored and who can access it.
- Encryption, backup, retention period, deletion process, and data residency.
- How the customer can export its project and audit history.
- How deletion is requested and verified, including backups and temporary
  copies.
- Who is notified, and within what agreed period, if a security incident or
  accidental disclosure is suspected.

The current SQLite workspace prototype stores metadata and hashes only; it
does not yet provide encryption-at-rest, role-based access, backup/restore,
retention scheduling, secure deletion, or a complete incident-response
workflow. Do not imply those controls are already implemented.

## 10. Product claims and liability boundaries

Use accurate language:

- "Decision-support prototype" rather than "certified controller".
- "Scenario result" rather than "guaranteed savings".
- "Forecast baseline" rather than "validated site forecast" unless site
  backtesting supports that claim.
- "Asset data supplied by the customer" rather than "verified equipment data"
  unless independently verified.
- "Offline recommendation for human review" rather than "automatic dispatch".

Do not promise compatibility with an untested device, guarantee an economic
outcome, or suggest that IslandOS replaces site operators, protection systems,
manufacturer procedures, or engineering sign-off.

## 11. Release gate for a real customer pilot

A pilot is not ready to start until all applicable items are checked:

- [ ] Customer authority and data-sharing permission confirmed.
- [ ] NDA/data-processing/security review completed where required.
- [ ] Processing environment approved; public demo excluded for confidential data.
- [ ] Data scope minimized and provenance recorded.
- [ ] Asset inventory and installed configuration reviewed.
- [ ] Hard constraints and critical-load policy approved by named customer authority.
- [ ] Pilot scope, baseline, KPIs, and acceptance criteria agreed in writing.
- [ ] Retention, export, deletion, and incident contacts agreed.
- [ ] Offline-only and human-review boundary understood by all participants.
- [ ] Reproducibility and dispute-handling procedure demonstrated.

This checklist is an internal product safeguard. It must be adapted to the
customer's jurisdiction, sector, procurement requirements, and site-specific
safety obligations by qualified professionals.
