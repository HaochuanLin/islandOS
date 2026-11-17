# Customer Personas — Working Hypotheses

**Status:** HYPOTHESIS ONLY — NOT VALIDATED BY CUSTOMER INTERVIEWS  
**Evidence note:** These are role-based discovery hypotheses derived from the product's intended workflow. They are not real named customers, interview-derived personas, or proof of demand.

## Persona A — Daily operator / energy or facility operator
**Job to be done:** Keep essential services available while operating generation, storage, grid supply, backup generation and flexible loads within equipment and service limits.

**Likely decisions:** Whether to charge or discharge storage, use grid or diesel supply, defer flexible demand, schedule water pumping / RO where relevant, and respond to forecast or equipment changes.

**Potential pain hypotheses (NOT VALIDATED):**
- Relevant data and constraints are spread across meters, spreadsheets, equipment interfaces and staff knowledge.
- Operators may rely on manual rules and may find it difficult to compare the cost and service consequences of alternatives.
- A recommendation without a clear rationale, uncertainty range and override path may not be trusted.

**What IslandOS would need to demonstrate:** understandable comparison of feasible alternatives, source and timestamp visibility, constraint checks, uncertainty disclosure, audit trail and explicit human approval.

**Likely objections to test:** inaccurate inputs, stale forecasts, too many alerts, recommendations that conflict with local operating knowledge, extra workload and unclear accountability.

## Persona B — Technical evaluator / energy manager / engineering lead
**Job to be done:** Determine whether a decision-support tool represents the site's assets, operating limits, data interfaces and reliability requirements accurately enough to evaluate.

**Potential evaluation criteria (NOT VALIDATED):** correct units, timestamps, topology and equipment parameters; independent physical and service-constraint audit; reproducible baseline comparison and transparent assumptions; integration effort, cybersecurity, data ownership and failure behavior; clear boundary between advisory recommendations and control authority.

**What IslandOS would need to demonstrate:** documented input contracts, validation failures that fail closed, replayable runs, model limitations, versioned configurations and an authorized read-only evaluation path.

**Likely objections to test:** incomplete equipment models, no measured site validation, integration burden, unsupported edge cases and liability.

## Persona C — Economic buyer / asset owner / finance or operations director
**Job to be done:** Decide whether the operational problem is material, whether a solution can be procured and supported, and whether expected value justifies total cost and risk.

**Potential evaluation criteria (NOT VALIDATED):** baseline operating cost and service performance; gross operating benefit under equivalent service, not just lower modeled energy use; software, integration, maintenance, training and internal labor costs; procurement path, budget owner, payback threshold and evidence quality; vendor accountability, data governance and operational liability.

**What IslandOS would need to demonstrate:** a customer-specific, auditable economic case with uncertainty and exclusions, plus a credible implementation and support plan.

**Likely objections to test:** savings too small or uncertain, integration costs, lack of procurement fit, unclear ownership of benefits and competing capital priorities.

## Persona D — Gatekeepers and ecosystem influencers
Potential roles include site owner, utility, EPC, O&M contractor, IT/security, regulator, financing partner and community/service authority. Their authority varies by jurisdiction and facility.

**Questions to resolve:** Who can authorize data access? Who approves electrical engineering changes? Who owns dispatch decisions? Who accepts operational liability? Who signs and funds a pilot?

Do not treat a technical champion, interviewee or prospective partner as a buyer or authorized pilot sponsor without confirmation.

## Persona validation record
For each persona, record evidence that the role exists in the target segment; actual responsibilities and decision rights; current tools and workflow; measurable pain and frequency; evaluation / procurement criteria; contradictory evidence and segment-specific variation; confidence level and source references.

**Current status:** all personas above remain hypotheses; no external validation is claimed.
