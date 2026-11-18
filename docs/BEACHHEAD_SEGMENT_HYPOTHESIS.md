# Provisional Beachhead Segment — Stage 9

**Status:** WORKING HYPOTHESIS — NOT CUSTOMER-VALIDATED  
**Decision status:** No segment has been selected from interview evidence. This document defines a testable starting hypothesis, not a market claim.

## 1. Primary segment hypothesis

**Owner-operated, energy-constrained facilities with hybrid distributed energy systems** that combine at least two controllable or schedulable resources (for example, grid import, diesel generation, battery storage, solar PV, wind, or flexible loads) and have a material critical-service requirement.

Typical candidate facility classes to investigate:
- Remote or weak-grid community / institutional microgrids
- Remote commercial or industrial facilities with on-site generation and storage
- Critical infrastructure facilities with hybrid backup and meaningful operating decisions

The initial product fit hypothesis is strongest where an accountable operator must coordinate several resources under changing forecasts, tariffs, fuel constraints or service requirements. IslandOS currently supports offline, advisory analysis; this is not a claim of control-system integration or field readiness.

## 2. Buying and operating roles to test

| Role | Hypothesized responsibility | Evidence required |
|---|---|---|
| Daily operator | Executes or recommends daily dispatch decisions | Observed workflow, decision frequency, current tools |
| Technical evaluator | Checks asset models, data interfaces, physical limits and cybersecurity | Written technical requirements and integration review |
| Economic buyer | Owns energy/O&M budget and approves software spend | Budget ownership, cost baseline, procurement path |
| Gatekeeper | Site owner, utility, EPC/O&M, IT/security or regulator | Written data/site permissions and approval requirements |

Do not infer buyer authority from job title. A technical champion is not automatically the budget owner.

## 3. Eligibility filters for market counting

Count a facility as **potentially eligible** only if all required conditions are evidenced:

1. Facility is in the selected geography and is operational.
2. It has a distributed/hybrid energy system or a documented weak-grid supply problem.
3. At least two resources or flexible demands create a real coordination decision.
4. It has an identifiable operator or organization accountable for energy/service outcomes.
5. A plausible data route exists for timestamped generation, load, tariff and asset constraints, subject to authorization.
6. There is a measurable operating or service outcome that could be compared against a baseline.
7. The organization could procure or authorize an advisory software evaluation.

Classify each facility as:
- **Eligible:** all mandatory filters evidenced.
- **Potential:** plausible fit but one or more filters unverified.
- **Excluded:** fails a mandatory filter or lacks a credible use case.
- **Unknown:** source does not permit classification.

Do not count Potential or Unknown as Eligible in the base-case SAM.

## 4. Explicit exclusions from the initial beachhead

Exclude from the first-pass addressable segment:
- Facilities with reliable, low-cost supply and no material dispatch decisions.
- Single-resource sites with no meaningful coordination problem.
- Sites where no accountable operator or buyer can be identified.
- Sites with no lawful/authorized route to the minimum operational data.
- Utility-scale generation market segments requiring grid-market bidding, protection certification or control functionality not present in IslandOS.
- Pure water-treatment procurement where the energy coordination problem is not independently material.
- Residential individual households and generic smart-home energy management.

These exclusions can be revisited only with evidence and a clearly separate product scope.

## 5. Falsification tests

Reject or narrow this segment if interviews and records show that:
- Existing EMS/SCADA or EPC/O&M contracts already solve the relevant coordination problem at acceptable cost.
- The cost/service consequence is too small or too infrequent to justify software and integration.
- Operators cannot or will not use an advisory workflow.
- Required data is unavailable, poor quality or cannot be shared.
- Economic buyers cannot identify a budget or procurement route.
- Site-specific engineering, cyber or liability requirements make the initial product scope infeasible.

## 6. Evidence register

| Evidence ID | Segment/geography | Source type | Date | Finding | Classification | Confidence | Counterevidence / gap |
|---|---|---|---|---|---|---|---|
| — | — | — | — | No external segment evidence entered yet | NOT VALIDATED | — | Interviews and source-backed facility records required |

**Current conclusion:** this is a product-fit hypothesis to guide discovery and desk research. It does not establish segment prevalence, market size, customer demand or willingness to pay.
