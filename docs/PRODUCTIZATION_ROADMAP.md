# IslandOS Productization Roadmap

**Product definition:** IslandOS is an AI-assisted, simulation-first energy and resource coordination decision-support platform for energy-constrained regions and distributed infrastructure.

**Product promise:** From Energy Data to Intelligent Decisions.

## Four-step product workflow

1. **INPUT** — organize energy supply, demand, assets, resource requirements, constraints, data quality, and provenance.
2. **PREDICT** — estimate future changes in relevant supply, demand, prices, availability, and system state, with uncertainty where supported.
3. **OPTIMIZE** — compare feasible operating and investment alternatives against explicit technical, service, economic, and environmental objectives.
4. **DECIDE** — communicate trade-offs, risks, assumptions, and recommendations for human review, with an auditable record.

The four steps describe the user-facing product workflow, not the number of internal packages or services.

## Scope and use-case discipline

IslandOS is designed for energy-constrained regions and distributed infrastructure where energy systems interact with essential resources or flexible processes. Potential application families include remote communities, distributed energy infrastructure, microgrids, water and pumping infrastructure, and industrial or commercial facilities with flexible loads, storage, or resource constraints. These are target application families, not claims that every sector is currently supported or validated.

The platform architecture is generic, but each customer engagement must select one bounded decision problem. RO desalination and the Nan'ao scenario remain early experimental examples, not the product identity, default customer, or limit of the platform.

## Target users and decision value

Potential users to investigate include energy service companies, microgrid developers, system integrators, infrastructure and facility operators, engineering consultants, project developers, and equipment solution providers. Customer discovery must distinguish the end user, decision owner, budget approver, and data owner.

IslandOS should help answer: What is the baseline? Which inputs are trusted? What may change? Which operating or equipment alternatives are feasible? How do they compare in total cost, reliability, resource service, emissions, and operational burden? Which assumptions dominate? When is an option not worth pursuing?

No savings, payback, or purchasing recommendation is valid without traceable site-specific inputs and disclosed assumptions.

## Current maturity and evidence boundary

| Stage | Current repository evidence | Not yet established |
|---|---|---|
| INPUT | CSV/XLSX onboarding, local-first site workspace, versioned asset records, source hashes, immutable run manifests, append-only audit chain, and verified whole-workspace SQLite backup/restore | Project-level portable export/import, raw source-file retention, managed multi-site storage, production live integration |
| PREDICT | Canonical multi-domain signal catalog, replaceable prediction candidates, rolling-origin model comparison, model/version and history-hash provenance, empirical error bands | Site-calibrated accuracy, transfer validation, calibrated uncertainty consistently propagated into optimization |
| OPTIMIZE | Forecast-to-joint battery/diesel schedule search, deterministic stress scenarios, policy comparison, service-equivalence gate, bounded heuristic and audit export | Broad asset coverage, calibrated probabilistic robust optimization, global optimality, validated savings |
| DECIDE | Forecast-led customer decision page, model provenance, hourly schedule comparison, JSON audit, simplified customer-entered economics, versioned local reference API, tenant-scoped site records and read-only telemetry | Production service/security operations, full lifecycle customer economics, usability evidence, site-verified decision reports |

The public Streamlit app is an interactive research prototype, not a live operational system. The earlier A–F engineering work established reusable foundations and offline workflows; the current six-stage acceptance definition is tracked separately in `docs/STAGE_ABC_CLOSEOUT.md`. The prior Stage F implementation refers only to canonical workflow integration, not the new real-deployment Stage F. Experimental modules elsewhere in the repository do not automatically form part of the hosted application.

## Productization principles

1. **One shared system model:** represent assets, energy/resource flows, constraints, and inventories consistently.
2. **Evidence before claims:** identify source data, units, time range, assumptions, baseline, model version, and limitations.
3. **Prediction is not optimization:** forecast outputs and uncertainty must be explicit downstream inputs; do not imply integration until tested.
4. **Feasibility before ranking:** enforce critical-service and equipment constraints before ranking alternatives. Report infeasibility honestly.
5. **Economics is first-class:** distinguish CAPEX, OPEX, maintenance, replacement, tariffs, fuel, and lifecycle assumptions. Report sensitivities and no-go conditions; do not manufacture ROI.
6. **Human-supervised decisions:** recommendations support qualified review; no autonomous control or safety certification is implied.
7. **Reusable core, bounded pilots:** build generic interfaces but validate one narrow use case at a time.
8. **AI with a defined job:** prediction, uncertainty analysis, physical simulation, and optimization are the principal analytical value. An LLM may assist explanation, not replace physics or validation.

## Delivery phases and exit gates

### Phase 1 — Product positioning and documentation alignment
- Use the same definition and four-step workflow across README, repository description, blueprint, roadmap, and demos.
- Distinguish external workflow from internal architecture.
- Label capabilities implemented, experimental, planned, or long-term.
- Keep RO/Nan'ao as bounded examples.
- **Exit:** a new reader can explain what IslandOS is, how it works, what runs today, and what remains unbuilt without contradictory definitions.

### Phase 2 — Unified system and data foundation
- Standardize project/scenario configuration, timestamps, units, provenance, quality, asset identity, constraints, and inventories.
- Define stable adapter and model-service interfaces; consolidate duplicate schemas.
- Ensure hosted and future desktop interfaces call shared domain services.
- **Exit:** one scenario is represented consistently across simulation, forecasting, optimization, and reporting.

### Phase 3 — Connected prediction, simulation, and optimization
- Standardize forecast contracts, chronological evaluation, model identity, horizon, uncertainty, and provenance.
- Feed forecast scenarios into a common physical evaluator.
- Evaluate candidates with consistent physics and hard constraints; compare transparent baselines.
- **Exit:** a reproducible run connects validated inputs, forecasts, physical evaluation, and candidate comparison without hidden future information.

### Phase 4 — Customer economics and decision reporting
- Establish a customer-confirmed baseline and decision question.
- Provide a first simplified CAPEX/O&M/NPV/payback screen using customer-entered annual bills, supplier costs, replacement assumptions, and sensitivity; expand coverage to fuel, demand charges, escalation, financing, taxes, and degradation.
- Report total-cost comparisons, sensitivity, service effects, assumptions, and explicit no-go/not-enough-evidence outcomes.
- **Exit:** a qualified reviewer can reproduce the comparison and understand why an option is or is not justified.

### Phase 5 — Bounded pilot and supervised workflow
- Select one customer segment and decision problem based on discovery, data access, and economic relevance.
- Begin with offline replay and read-only shadow mode; obtain site-engineer review.
- Define security, safety, approval, rollback, and acceptance requirements before any control integration.
- **Exit:** a named decision owner accepts the methodology and deliverables against pre-agreed criteria.

### Phase 6 — Product interface and deployment maturity
- Guide users through INPUT → PREDICT → OPTIMIZE → DECIDE.
- Surface data quality, maturity, assumptions, uncertainty, infeasibility, and audit history.
- Keep interfaces on shared domain services; add operational controls according to validated user needs.
- **Exit:** independent users can complete a bounded workflow and reproduce its report without developer assistance.


### Stage F — unified customer workflow and deployment handoff

- Route customer-facing forecast and optimization pages through the same canonical signal catalog used by onboarding; do not duplicate signal semantics in UI code.
- Keep INPUT provenance, PREDICT model identity/backtests/error bands, OPTIMIZE feasibility/service-equivalence checks, and DECIDE audit exports visible in one reproducible path.
- Connect the local reference API only through explicit service boundaries; retain loopback-only defaults and read-only telemetry.
- Align README, product blueprint, maturity labels, and runnable workflow documentation with merged code.
- **Exit:** the customer decision page uses the canonical forecast catalog; an integration test covers catalog → forecast → joint optimizer; docs describe actual mainline capability and remaining production gaps. This is still an offline research workflow, not site validation or production SaaS.

## Customer discovery

Ask which recurring decision is costly or difficult; who experiences it, owns it, approves budget, and controls data; what baseline process costs; which data can be provided and under what permissions; what technical/commercial/security constraints apply; what deliverable changes a decision; and what evidence would justify paying for a bounded analysis or pilot. Record roles, exact statements, evidence, and unresolved assumptions. Interest is not purchase intent.

## Explicit non-claims

IslandOS does not currently claim universal plug-and-play integration, a validated multi-signal forecast service for arbitrary sites, globally optimal scheduling, certified safety, autonomous learning, live equipment control, commercial deployment, field-proven savings, or bankable ROI. Each requires separate technical, site, and commercial evidence.
