# Stage F — unified customer workflow and deployment handoff

**Status:** Integration increment in progress; this document records the exact scope and evidence gate, not a production-readiness claim.

## Why Stage F follows A–E

- A established the main branch as the sole integration baseline and designated canonical module boundaries.
- B integrated customer CSV/XLSX onboarding, a local-first site workspace, asset records and provenance.
- C integrated a canonical multi-domain signal catalog and a replaceable prediction engine with chronological replay.
- D integrated forecasts into a bounded joint battery/diesel schedule search with service-equivalence checks.
- E added a versioned local reference API, tenant-scoped identity/site records and read-only telemetry.
- F closes the customer-facing handoff: the same signal semantics must flow from onboarding through forecast and optimization, while the user sees traceable provenance, assumptions, limits and a reproducible report.

## Stage F implementation scope

1. Route the forecast-led customer decision page through `forecast_site_signals`, the same canonical catalog used by onboarding, rather than rebuilding signal semantics and constructing individual prediction requests in UI code.
2. Preserve explicit units, model IDs/versions, rolling-origin metrics, input-history hashes and aligned target timestamps through the dispatch adapter.
3. Keep the optimizer offline and fail closed on missing/misaligned signals or unit errors; keep service-equivalence gating and the no-device-write boundary.
4. Align README, product blueprint and productization roadmap with merged A–E code and the actual Stage F integration.
5. Retain a reproducible integration test that starts with canonical hourly histories, forecasts the four dispatch signals, and executes the joint optimizer.

## Stage F acceptance evidence

- [ ] Customer-facing forecast-led page calls the canonical signal catalog.
- [ ] Integration test covers canonical catalog → prediction engine → joint dispatch optimizer.
- [ ] README and blueprint describe actual mainline capability and do not call delivered D/E work merely planned.
- [ ] Exact-head CI passes before merge.
- [ ] No live control, field validation, production SaaS, or verified savings claims are introduced.

## Deliberate exclusions

Stage F does not turn the local API into a public service. Managed database/object storage, TLS termination, secrets management, MFA, rate limiting, backup/restore, penetration testing, device identity, vendor protocol adapters, site acceptance and any device-write path remain separate work requiring security and engineering review.
