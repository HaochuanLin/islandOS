# Market Sizing & Market Entry Method — Stage 9

**Status:** METHOD DEFINED — QUANTIFICATION NOT STARTED  
**Evidence status:** No defensible facility-count dataset, price evidence, TAM, SAM, SOM or market-share estimate is established in this repository.

## 1. Objective

Estimate a reachable market for IslandOS without multiplying broad energy-sector statistics into an invented software market. The unit of analysis is an **eligible facility / buying organization**, not population, installed renewable capacity, megawatts, electricity demand or all microgrids worldwide.

Stage 9 has two separate outputs:
1. **Problem scale:** how many facilities plausibly experience the coordination problem.
2. **Commercial market:** how many such facilities can technically and commercially be served, at a price and sales capacity supported by evidence.

Do not conflate them.

## 2. Segment and geography gate

Before numeric sizing, select one narrowly defined facility segment and one initial geography using Stage 7 discovery evidence. Record:
- facility definition and exclusions;
- asset configurations and critical-service characteristics;
- buyer, technical evaluator and operator roles;
- procurement route and budget owner;
- legal/data access constraints;
- reason this geography is reachable by the team and any delivery partner.

Until this gate is satisfied, keep country-level facility counts and revenue estimates blank.

## 3. Counting funnel

For a selected geography, build a deduplicated facility-level inventory:

1. **Universe:** all facilities in the relevant official registry or other traceable source.
2. **Operational:** remove closed, planned, duplicate or decommissioned facilities.
3. **Energy-system fit:** retain facilities with documented hybrid/distributed assets or relevant weak-grid exposure.
4. **Coordination fit:** retain facilities with multiple schedulable resources / flexible loads and an accountable operator.
5. **Data and technical fit:** retain facilities with a plausible authorized data route and enough asset information for an advisory assessment.
6. **Commercial reachability:** retain facilities with an identifiable buying organization and plausible procurement route.

Record counts at every filter, the source, date, geography, deduplication key and confidence. A missing filter value is **Unknown**, not a pass.

## 4. Definitions and formulas

Use facility counts first; translate to revenue only after pricing evidence exists.

- **TAM (problem-fit universe):** all operational facilities in the defined segment/geography that meet the documented problem-fit filters, whether or not IslandOS can reach them immediately.
- **SAM (serviceable available market):** the TAM subset meeting current product, data, jurisdiction, language, integration and delivery constraints.
- **SOM (serviceable obtainable market):** the subset plausibly reachable within a stated period given actual sales capacity, procurement cycles, conversion evidence and implementation/support capacity.

For a facility-count view:

`TAM_facilities = count(unique eligible facilities after problem-fit filters)`

`SAM_facilities = count(unique TAM facilities passing current serviceability filters)`

`SOM_facilities = min(SAM facilities, evidence-based sales/implementation capacity over the stated period)`

For a revenue view, only when price evidence exists:

`Annual recurring revenue opportunity = eligible paying organizations × evidenced annual contract value`

Do not apply a generic SaaS multiple, arbitrary penetration rate or assumed price to produce a revenue TAM. If pricing is unknown, report facility counts only and label revenue sizing **NOT ESTIMABLE**.

## 5. Scenario and uncertainty treatment

Report low / base / high ranges only when each range is generated from explicit, sourced filter uncertainty:
- Low: conservative confirmed eligible count; Unknown facilities excluded.
- Base: best-supported classification using documented evidence.
- High: includes a clearly identified subset of Potential facilities, never facilities known to be excluded.

Show the effect of each uncertain filter separately. Do not use an arbitrary percentage haircut or claim statistical confidence where the source is not a representative sample.

## 6. Source hierarchy

Prefer sources in this order:
1. Government, regulator, utility or public asset registries with facility-level records.
2. Official electrification / mini-grid databases and project registries with documented methodology.
3. Multilateral development-bank and development-agency project datasets.
4. Published operator, EPC or asset-owner portfolios with transparent scope and date.
5. Peer-reviewed studies and reputable industry reports for context or cross-checking.

Examples of source families to investigate after geography selection include national energy regulators and rural electrification agencies, utility and mini-grid registries, World Bank/ESMAP energy access datasets, IRENA statistics, IEA publications and development-bank project databases. These are research leads, not evidence that any particular facility is eligible.

For every source, capture publisher, exact title/dataset, URL or persistent identifier, publication/update date, access date, geography, coverage, unit, inclusion/exclusion rules, known omissions and license/access constraints.

## 7. Market-entry logic

Evaluate each candidate geography on:
- documented target-facility count and concentration;
- energy price / fuel logistics / outage exposure only where reliable sources exist;
- presence of operators, EPCs, microgrid developers and O&M providers;
- procurement and budget ownership;
- data ownership, cybersecurity and connectivity;
- local engineering, support and liability requirements;
- competition and incumbent EMS/SCADA coverage;
- feasible channel: direct sale, EPC/O&M partnership, developer portfolio or funded technical evaluation.

A partner route remains **exploratory** until a named organization confirms interest and responsibilities in writing. Do not claim a partnership based on a public project or personal introduction.

## 8. Required audit trail

Every reported number must have:
- a unique source ID and citation;
- source date and access date;
- geography and facility definition;
- raw count and deduplication method;
- every filter and its numerator / denominator;
- treatment of missing and duplicate records;
- calculation formula and reproducible worksheet/script;
- low/base/high assumptions and counterevidence;
- reviewer and review date.

An independent reviewer must be able to reproduce the totals from the source register.

## 9. Stage 9 acceptance gate

Stage 9 is complete only when:
- Stage 7 supports a specific segment and buying path, or the hypothesis is explicitly rejected;
- one initial geography is selected with a documented rationale;
- facility-level source records are traceable and deduplicated;
- all eligibility filters are independently recalculable;
- TAM/SAM/SOM definitions and uncertainty are explicit;
- any revenue estimate uses evidenced pricing and capacity;
- source limitations and contradictory evidence are visible.

**Current result:** no numerical TAM/SAM/SOM or market-share claim is made. Market size remains **NOT ESTIMABLE** pending target-segment, geography, facility inventory and price evidence.
