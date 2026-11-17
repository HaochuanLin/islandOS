# Customer Interview Guide

**Status:** READY FOR FIELD USE; NO INTERVIEWS RECORDED  
**Validation status:** NOT VALIDATED

## 1. Before the conversation
- Identify the facility segment and the respondent's actual role(s).
- State that this is product discovery for an early research prototype, not a sales commitment or safety-certified product.
- Ask permission to take notes and clarify whether recording or anonymized quotation is allowed.
- Do not request credentials, personal data, confidential site data or restricted operational details.
- Do not promise savings, deployment, integrations or autonomous control.

Suggested opening:

> We are researching how facilities coordinate energy supply, storage and flexible services. We are trying to understand your current process and its difficulties. This is not a sales pitch. IslandOS is an early, simulation-first decision-support prototype, and we have not established site-level performance or customer savings.

## 2. Core questions — ask about actual past behavior
1. Could you walk me through the last time you had to make a difficult energy or service-operation decision?
2. What triggered the decision? What information did you have at that moment?
3. Which systems, spreadsheets, meters, forecasts or people did you consult?
4. Who made the final decision, and who could override it?
5. What alternatives did you consider? Why did you choose the one you used?
6. What happened afterward? Was there a cost, outage, service shortfall, fuel issue, curtailment or equipment concern?
7. How often does a similar situation occur? What records could verify that frequency?
8. What part of the process consumes the most time or creates the most uncertainty?
9. What do you currently use to solve this problem? What works well, and what does not?
10. Have you tried another tool or process? Why was it adopted, rejected or abandoned?

Avoid leading questions such as “Would AI optimization save you money?” Prefer “How do you currently measure the cost of this decision?”

## 3. Technical evaluator questions
1. Which signals are available, at what interval, with what units and time zone?
2. How are missing, delayed, implausible or conflicting readings handled?
3. Which assets and operating constraints must any schedule respect?
4. Which constraints are hard safety/service limits, and who is authorized to define them?
5. How are forecasts evaluated today? Which baselines and error metrics are accepted?
6. What independent audit would be required before you trusted a recommendation?
7. What integration, network, identity, cybersecurity and data-retention requirements apply?
8. Would retrospective replay or read-only Shadow Mode be an acceptable first evaluation? What approvals are required?
9. What conditions would cause you to reject a recommendation or stop a trial?

## 4. Economic buyer questions
1. Which budget owns energy operations, software, engineering integration and maintenance?
2. Which cost categories are material and can be measured from records?
3. What is the current baseline period and how is service equivalence defined?
4. What evidence is required to attribute a benefit to a new decision process?
5. Who approves a purchase and what procurement route applies?
6. What are the typical approval steps and timing?
7. Which costs would the facility incur for software, integration, training, support and ongoing validation?
8. What economic threshold or payback period would make an evaluation worth considering?
9. Is there a budget for a paid evaluation or pilot? If not, what would need to change?

Do not interpret a hypothetical threshold as a purchase commitment.

## 5. Concept test — only after the problem interview
Describe the proposed workflow neutrally:

> IslandOS aims to combine authorized operational inputs, forecast relevant conditions, compare resource strategies against declared constraints, and produce an auditable recommendation for human review. The current prototype is simulation-first and advisory-only.

Then ask which part fits the workflow; what information is missing or misleading; what would make the recommendation unsafe or unusable; what is needed before acting on it; who must approve data access, evaluation and procurement; and which existing product it must complement or replace.

Do not ask only whether the respondent “likes” the concept.

## 6. Close
- Ask what important issue was missed.
- Ask whether a follow-up with another role would be appropriate; do not assume an introduction is consent.
- Ask whether anonymized historical data could be considered under a written authorization process.
- Confirm what may be quoted, shared or retained.
- Thank the respondent; do not imply a partnership or pilot has been agreed.

## 7. Interview record template
Copy one record per conversation:

| Field | Entry |
|---|---|
| Record ID / date / interviewer | |
| Consent to notes / recording / anonymized quote | |
| Facility segment / geography | |
| Respondent role(s) | User / technical evaluator / economic buyer / gatekeeper |
| Last concrete decision described | |
| Current process, tools and data | |
| Frequency and consequence (reported vs measured) | |
| Existing workaround / incumbent solution | |
| Asset and service constraints | |
| Data availability / authorization status | |
| Budget owner / procurement route (if known) | |
| Concept reaction after problem discussion | |
| Evidence type and source reference | |
| Hypotheses supported / contradicted / unresolved | |
| Counterevidence / uncertainty | |
| Follow-up and owner | |
| Confidentiality / redaction notes | |

**Current repository record count:** 0 interview records. No external feedback is claimed.
