# Asset operational state and readiness

## Purpose

`islandos_core.operational_state` adds a time-stamped, provenance-bearing
operational observation layer alongside the relatively static asset registry.
It answers a narrow question: are the supplied asset-state observations
sufficiently fresh, confirmed, and online for a dispatch *screening* workflow?

It does not establish that the observations came from a live device unless the
source reference and ingestion process prove that. It does not issue commands.

## Data contract

Each `AssetOperationalState` contains:
- asset and site identifiers;
- one of `online`, `offline`, `maintenance`, `fault`, or `unknown`;
- a timezone-aware observation timestamp;
- a source reference and explicit confirmation flag.

Naive timestamps are rejected. The caller supplies an explicit evaluation time
and maximum acceptable age. The default freshness window is 15 minutes; it is a
configurable screening policy, not a universal industrial standard.

## Readiness rules

For assets in scope (all supplied assets, or only assets connected in an
optional site topology):
- missing, duplicate, unknown-asset, or cross-site observations are blockers;
- stale or future-dated observations are blockers;
- unconfirmed observations are blockers;
- unavailable assets and any state other than `online` are blockers;
- no state is silently inferred from asset category or static nameplate data;
- when a topology is supplied, its structural readiness is revalidated first;
  unconfirmed or inconsistent topology blocks the operational gate.

The result is a read-only `can_dispatch_screen` gate. It is not permission to
control the system, nor does it certify electrical connectivity, safety, or
actual equipment health.

## Integration

Use
`islandos_core.application.evaluate_site_operational_readiness(...)`
from client interfaces. This keeps the policy in the shared application layer
rather than duplicating it in Streamlit and the desktop shell.

## Boundaries and next work

The current layer does not ingest telemetry protocols, establish clock
synchronization, debounce state transitions, reconcile conflicting sources,
or persist state history. Those need explicit source adapters, clock-quality
metadata, conflict policy, and audit retention. The state is a snapshot input
to future simulation/optimization readiness, not a physical simulation itself.
