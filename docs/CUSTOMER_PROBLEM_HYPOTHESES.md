# Customer Problem Hypotheses

**Status:** ALL HYPOTHESES NOT VALIDATED  
**Purpose:** Make the customer problem falsifiable before building commercial claims or adding product features.

## Hypothesis register
| ID | Hypothesis to test | Observable evidence | Disconfirming evidence | Status |
|---|---|---|---|---|
| H1 | Some energy-constrained facilities coordinate multiple resources using fragmented tools or manual processes. | Operator demonstrates spreadsheets, separate interfaces, manual hand-offs or repeated reconciliation. | A reliable integrated EMS already handles the relevant decisions with low operator burden. | NOT VALIDATED |
| H2 | Forecast variation creates avoidable cost or service risk when decisions are made too early or too late. | Recent examples where forecast errors changed dispatch, fuel use, curtailment or service outcomes. | Forecasts rarely affect decisions or the consequences are immaterial. | NOT VALIDATED |
| H3 | Operators need to compare several feasible operating strategies, not merely receive a single forecast. | Evidence of trade-off decisions across cost, reliability, equipment life and flexible service. | Existing rules already provide sufficient alternatives and explanation. | NOT VALIDATED |
| H4 | Technical evaluators require transparent physical constraints, data provenance and replayable audit records before trusting recommendations. | Written evaluation criteria, acceptance tests or rejected-tool examples. | These controls are not material to procurement or are fully covered by existing systems. | NOT VALIDATED |
| H5 | A read-only decision-support layer can fit into an existing workflow without taking control authority. | A defined review workflow, accountable approver and willingness to test recommendations against actual operations. | No clear user, no workflow slot, or no value without automatic control. | NOT VALIDATED |
| H6 | Operating-cost or service improvements can justify software and integration costs in at least one narrow segment. | Comparable baseline records, cost ownership, credible benefit mechanism and buyer-defined threshold. | Benefits are too small, not attributable, or outweighed by implementation/support costs. | NOT VALIDATED |
| H7 | A facility has sufficient authorized, timestamped operational data for retrospective evaluation. | Data inventory, sample schema, data-quality report and written permission. | Data is unavailable, inaccessible, poor quality or cannot legally be shared. | NOT VALIDATED |
| H8 | There is a reachable procurement route and identifiable budget owner for this category of tool. | Named role (not necessarily person), procurement steps, budget category and decision timeline. | No budget owner, no procurement category or incumbent contract prevents adoption. | NOT VALIDATED |

## Segment-specific questions
Do not assume that island microgrids, remote communities, telecom sites, water facilities, industrial microgrids and distributed infrastructure have the same problem or buying process. For each segment, test grid connection quality and outage exposure; generation, storage and flexible-load mix; critical-service obligations and outage cost; tariff structure and fuel logistics; current EMS / SCADA / O&M arrangements; operator staffing and technical capability; asset ownership and decision authority; procurement and regulatory constraints.

## Evidence rules
- A respondent's opinion is a reported perception, not measured operating performance.
- A single anecdote does not establish prevalence across a market.
- A synthetic scenario demonstrates model behavior only; it does not validate H1–H8.
- A modeled cost difference is not a verified customer saving.
- An expression of interest is not willingness to pay; willingness to pay requires a concrete price / procurement test.
- A partner introduction is not a partnership agreement.
- Contradictory evidence must remain in the register.

## Update protocol
For each hypothesis, store status (NOT VALIDATED, SUPPORTED — LIMITED, CONTRADICTED, or VALIDATED WITHIN DEFINED SCOPE), evidence IDs, sample size, segment/geography, date, confidence, counterevidence, unresolved confounders and next test.

Do not use VALIDATED without multiple independent evidence sources and a stated scope. Stage 7 starts with every hypothesis marked **NOT VALIDATED**.
