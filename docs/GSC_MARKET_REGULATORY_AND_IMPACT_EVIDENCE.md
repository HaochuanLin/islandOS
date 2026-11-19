# GSC Phase 1 evidence supplement — market, customer, impact, regulation and funding

Status: research and synthetic software-screening evidence only. This document does not claim customer interviews, a pilot partner, measured site performance, regulatory approval, secured funding, or commercial traction.

## 1. Market context and initial serviceable segment

### What the external evidence supports

- The 2024 *State of the Global Mini-grids Market Report* reports that global mini-grid installations have grown sixfold since 2018. Between 2018 and 2024, diesel's share of mini-grid capacity fell from 42% to 29%, while solar PV's share rose from 14% to 59%. The report also records more than USD 2.5 billion in committed sector funding in 2023 and private investment approaching USD 600 million in 2022. These are indicators of a growing and changing infrastructure base—not the revenue or addressable market of islandOS. Source: Mini-Grids Partnership / SEforALL, 2024 report: https://www.minigrids.org/global-market-report-2024/
- The 2026 *Tracking SDG 7* report states that 655 million people lacked electricity access in 2024; 86% of this population was in Sub-Saharan Africa. This establishes the scale and geography of the energy-access challenge, but people without electricity are not automatically customers for an energy-management software product. Sources: UN SDG Goal 7 (2026): https://unstats.un.org/sdgs/report/2026/Goal-07 ; WHO/SDG7 joint release: https://www.who.int/news/item/24-06-2026-655-million-people-still-living-without-electricity-underscore-urgent-need-to-deliver-on-universal-energy-access-target
- IRENA's 2025 SIDS grid-modernisation toolkit addresses storage, grid modernisation and resilient island power systems. It supports island and remote-grid relevance as a distinct use-case family, not a numerical estimate of islandOS customers. Source: https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2025/Dec/IRENA_PAR_Powering_resilient_islands_2025.pdf
- Nigeria's Rural Electrification Agency describes DARES as a USD 750 million World Bank-funded programme targeting 1,225 mini-grids and electricity access improvements for 17.5 million people. These are programme targets, not completed installations or an islandOS market count. Source: https://nep.rea.gov.ng/dares.html

### Initial customer segment (commercial hypothesis)

The first segment should be defined by operating conditions rather than by geography alone:

1. Small or mid-sized hybrid mini-grid operators and energy-service companies managing solar PV, batteries and diesel backup.
2. Remote critical facilities with a mixed energy supply and controllable loads (for example water pumping/treatment, cold storage, clinics or productive-use equipment).
3. Operators with recurring planning decisions, fragmented but exportable operating data, identifiable equipment constraints and an accountable operations manager.

A site is not a qualified prospect merely because it is remote or has renewable energy. It must have a decision problem islandOS can actually address, sufficient authorised data, compatible asset configuration, a buyer and a plausible procurement route.

### Market sizing discipline

Do not label the global mini-grid sector's investment or electricity-access population as islandOS TAM. The 2024 report's sixfold installation growth and USD 2.5bn+ committed sector funding describe the underlying infrastructure market, not spend on decision-support software.

No defensible software TAM/SAM/SOM can yet be calculated from the available evidence because there is no defined launch geography, verified count of compatible sites, procurement filter, pricing evidence or willingness-to-pay data. Use a transparent bottom-up method after choosing the first country and buyer type:

- TAM = count of all facilities in the defined geography meeting the target asset/configuration profile × an independently tested annual contract value.
- SAM = TAM facilities filtered for data availability, compatible equipment, legal/procurement access and a reachable buyer.
- SOM = SAM facilities realistically reachable over a stated period, constrained by sales capacity, implementation capacity and partner access.

Until those inputs exist, report the segment definition and the data required; do not publish an invented dollar market size.

## 2. Primary customer persona — operational buyer hypothesis

**Persona: Hybrid Microgrid Operations Manager**

- **Role:** Runs day-to-day operations for a small remote mini-grid or a portfolio of remote energy assets; reports to the site owner, utility, energy-service company or project operator.
- **Accountability:** Keep critical loads served; manage solar variability, battery state, diesel backup, grid imports where available, and flexible demand; explain operating decisions and cost deviations.
- **Current workflow hypothesis:** Meter exports, spreadsheets, tariff sheets, equipment manuals, fixed rules and operator experience. The actual workflow must be confirmed through interviews; it is not an observed fact.
- **Recurring decision:** Before the next operating period, decide what to run, when to charge/discharge, how much reserve to retain, when diesel or grid imports are justified, and which flexible loads can move without violating service requirements.
- **Pain hypothesis:** Inputs live in separate files; the operator may lack a modelling specialist; the effect of a schedule on fuel/grid cost, reserve and essential service is hard to compare consistently.
- **Buying trigger:** Repeated avoidable fuel/peak-import costs, unreliable service, increasing asset complexity, or a requirement to produce defensible operating reports.
- **Purchase criteria:** Verified net value after integration/training/maintenance cost; fit with existing equipment and data exports; reliability and service constraints preserved; explainable assumptions; human approval; low operational and cyber risk.
- **Buyer vs user:** The operations manager is the daily user and technical champion. The facility owner, mini-grid operator, energy-service company or portfolio manager is the likely budget holder.
- **Likely objection:** “Our existing controller/EMS already does this” or “The data and integration effort will cost more than the savings.” IslandOS must prove a gap and net benefit rather than claim superiority over established EMS platforms.

This is a hypothesis-based persona derived from sector research and engineering reasoning. No interview, quote, willingness-to-pay signal or purchasing decision is claimed.

## 3. Reproducible synthetic impact-screening case

A GitHub Actions run executed the repository's 168-hour synthetic forecast-to-dispatch workflow. Run ID: 44430909326. Source commit: 348698156520c25b12bc44c8d7f52ba2a1d94eea. The run completed successfully and produced CSV/JSON audit outputs.

### Configuration and evidence boundary

- 168 hourly synthetic input rows; first 24 hours used as warm-up; 144 forecast/dispatch comparison hours (six days).
- Simplified RO load: 10 kW; specific energy: 4 kWh/m³; tank capacity: 50 m³; initial water inventory: 10 m³; minimum run: one hour.
- The demand model is a trailing 24-hour mean baseline, not a trained AI model.
- Renewable-surplus, grid-price, off-peak, diesel-displacement, grid-availability and backup-availability signals are timestamp-aligned supplied inputs; this workflow does not forecast them.
- All inputs are synthetic. This is software screening, not measured site evidence, a field trial, verified savings or a safety assessment.

### Forecast result — a limitation, not a success claim

On 144 rolling-origin timestamps:
- Trailing-day-mean demand forecast MAE: 0.1627 m³/h; RMSE: 0.1996 m³/h.
- Previous-day baseline MAE: 0.0923 m³/h; RMSE: 0.1142 m³/h.
- The implemented trailing-day mean therefore performed worse than the previous-day baseline on this synthetic case (about 76% higher MAE and 75% higher RMSE).

Interpretation: this run does not support a forecast-accuracy advantage. It shows why baseline comparison is mandatory and why the forecast module needs refinement before any performance claim.

### Strategy comparison — six-day synthetic screening

| Strategy | Water produced | Water served | Unmet demand | Grid energy to RO | Modelled grid cost |
|---|---:|---:|---:|---:|---:|
| No RO baseline | 0 m³ | 10.0 m³ | 162.02 m³ | 0 kWh | 0.00 |
| Surplus only | 30 m³ | 40.0 m³ | 132.02 m³ | 0 kWh | 0.00 |
| Off-peak only | 120 m³ | 128.70 m³ | 43.32 m³ | 480 kWh | 57.60 |
| Hybrid surplus then off-peak | 150 m³ | 158.70 m³ | 13.32 m³ | 480 kWh | 57.60 |

The hybrid case used 120 kWh of the 308.67 kWh synthetic renewable-surplus signal and 480 kWh of off-peak grid energy. Relative to off-peak-only, it produced and served 30 m³ more water with the same modelled grid energy and grid cost, but still left 13.32 m³ unmet demand. This is a scenario comparison under supplied assumptions, not proof of real savings or service reliability. The model does not price the opportunity cost of renewable surplus, backup energy cost is not available, and the result does not establish that water demand was fully met.

### Safe proposal wording

“The reproducible six-day synthetic case demonstrates that the current workflow can compare alternative operating rules and expose trade-offs between water service, renewable-surplus use and grid expenditure. In this scenario, the hybrid rule served 30 m³ more water than off-peak-only at the same modelled grid cost, while 13.3 m³ of demand remained unmet. The tested trailing-day-mean forecast did not outperform a previous-day baseline, so forecast improvement remains a development requirement. These are synthetic software-screening results, not measured site outcomes.”

## 4. Regulatory pathway — Nigeria as an illustrative candidate jurisdiction only

No first pilot country or site has been selected. Nigeria is included here as a concrete regulatory case study because it has a current mini-grid framework and a major distributed-renewables programme; this does not mean islandOS has a Nigerian pilot, partner or approval.

The Nigerian Electricity Regulatory Commission (NERC) published the **Mini-Grid Regulations 2026 (NERC-R-001-2026)**. The regulator's current guidance classifies isolated mini-grids up to 5 MW and interconnected mini-grids up to 10 MW; it describes registration for isolated projects up to 100 kW and permits for larger projects. The regulations cover permits/registration, technical operation, service quality, health and safety, environmental protection, metering/billing, grid arrival/transition, tariffs and commercial arrangements. Official sources:
- NERC 2026 mini-grid guidance: https://nerc.gov.ng/need-help/services/apply-for-mini-grid-permit-2/
- Full 2026 regulation: https://nerc.gov.ng/wp-content/uploads/2026/04/Mini-Grid-Regulations-2026.pdf

The 2026 regulations also recognise that state electricity regulatory commissions may have jurisdiction over intrastate electricity activities where a state has assumed regulatory oversight. A real project must therefore confirm the site state and the competent regulator; it must not assume that NERC is always the sole authority.

**Implication for islandOS now:** the current product is a simulation-first, advisory-only software prototype with no live control path. The proposal should not imply that islandOS itself is a licensed mini-grid operator or that it has received a mini-grid permit. For a read-only pilot, the immediate gates are site-owner authorisation, data-access permissions, cybersecurity/privacy review, contract/liability review, and confirmation that the tool does not issue operational commands. Any future connection that influences dispatch, protection, metering, export or equipment control requires site-specific engineering and regulatory review, including the applicable technical codes, interconnection agreement and operator approvals. A qualified local engineer and counsel must review the final deployment design.

## 5. Funding and partnership pathway — realistic eligibility

### Relevant ecosystem instruments

- **Nigeria DARES (World Bank-funded, implemented through Nigeria's Rural Electrification Agency):** programme target of 1,225 mini-grids and 17.5 million people reached. This is a strong ecosystem signal and potential route to identify developers/operators, but it is not an automatic grant to a student software team. The programme is directed at distributed-renewable energy access deployment. Source: https://nep.rea.gov.ng/dares.html
- **Universal Energy Facility (UEF), managed by Sustainable Energy for All:** results-based incentives for eligible organisations deploying mini-grids and providing verified electricity connections in selected African countries. Published eligibility includes a legally registered for-profit company operating in the host country, at least one existing operational mini-grid, financial capacity and compliance with technical, environmental/social and gender requirements. This makes UEF a poor direct fit for islandOS at its current stage; a qualified mini-grid developer could be a future implementation partner. Sources: https://www.seforall.org/programmes/universal-energy-facility/universal-energy-facility-mini-grids and https://www.seforall.org/programmes/universal-energy-facility/impacts-and-results
- **University innovation/research funding and challenge grants:** the most realistic near-term route for a student team to fund software validation, supervised research, travel and a small data-integration prototype. The application should be tied to a named university scheme and its eligibility rules; no award is assumed.
- **Operator / energy-service-company pilot partnership:** likely the most valuable non-dilutive support is access to authorised historical data, a technical reviewer and a read-only shadow evaluation. In-kind data access and engineering time may be more attainable than a large grant at this stage.

### Funding-stage fit

| Stage | Realistic route | What must exist first |
|---|---|---|
| Current student prototype | University innovation fund, competition award, supervised research grant | Working demo, documented synthetic evidence, scoped budget and academic oversight |
| First validation | Operator/ESCO collaboration; small applied-research or pilot grant | Named site, data permission, qualified engineer, evaluation protocol and cybersecurity review |
| Commercial pilot | Country-specific energy-access programme or developer consortium | Registered eligible applicant/partner, site approvals, costed deployment, safeguards and measurable KPIs |
| Scale-up | Results-based finance, development-finance or climate-finance programme through eligible project developers | Proven deployments, audited reporting, legal entity, operational track record and verified results |

Do not state that DARES, UEF, GCF or any other funder has an open award available to islandOS unless a current call explicitly confirms eligibility and dates. In particular, UEF's published mini-grid criteria require an established in-country operator with an existing operational mini-grid; islandOS does not meet that profile today.

## 6. Proposal changes recommended

1. Replace the old mini-grid count from the 2019 World Bank report with the 2024 market report's sixfold installation growth and changing solar/diesel mix, while clearly stating that this is infrastructure context rather than software TAM.
2. Add the 2026 electricity-access evidence and Nigeria DARES programme targets as context, not customer counts.
3. Replace the existing persona table with the more concrete operator persona above and keep the “hypothesis, not interview evidence” label.
4. Add the synthetic case's actual outputs, including the weaker-than-baseline forecast result. Do not suppress the negative result.
5. Replace generic regulation text with the Nigeria 2026 case study plus the explicit caveat that the first geography remains unselected and state-level jurisdiction may matter.
6. Replace generic funding language with stage-matched routes and clearly state that current student-team eligibility is limited.

## References

1. Mini-Grids Partnership / SEforALL (2024), *State of the Global Mini-grids Market Report 2024*: https://www.minigrids.org/global-market-report-2024/
2. United Nations Statistics Division (2026), *SDG Goal 7*: https://unstats.un.org/sdgs/report/2026/Goal-07
3. WHO / SDG7 custodian agencies (24 June 2026), electricity-access joint release: https://www.who.int/news/item/24-06-2026-655-million-people-still-living-without-electricity-underscore-urgent-need-to-deliver-on-universal-energy-access-target
4. IRENA (2025), *Powering resilient islands: Grid modernisation toolkit for SIDS*: https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2025/Dec/IRENA_PAR_Powering_resilient_islands_2025.pdf
5. Nigeria Rural Electrification Agency, DARES programme: https://nep.rea.gov.ng/dares.html
6. Nigerian Electricity Regulatory Commission (2026), *Mini-Grid Regulations 2026*: https://nerc.gov.ng/wp-content/uploads/2026/04/Mini-Grid-Regulations-2026.pdf
7. NERC, Mini-Grid Regulations 2026 guidance: https://nerc.gov.ng/need-help/services/apply-for-mini-grid-permit-2/
8. Sustainable Energy for All, Universal Energy Facility mini-grid programme: https://www.seforall.org/programmes/universal-energy-facility/universal-energy-facility-mini-grids
9. Sustainable Energy for All, UEF results: https://www.seforall.org/programmes/universal-energy-facility/impacts-and-results
10. islandOS synthetic evidence workflow run 44430909326, source commit 348698156520c25b12bc44c8d7f52ba2a1d94eea (artifact archived with run; expires 19 December 2026).
