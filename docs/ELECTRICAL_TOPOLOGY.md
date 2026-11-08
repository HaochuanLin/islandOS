# Electrical topology: structural validation

## Purpose

`islandos_core.electrical_topology` adds a site-level description of electrical
buses, branches, and equipment port connections. It is the next data-model layer
after the confirmed asset registry and asset-to-energy-model adapter.

The first increment deliberately validates declarations rather than simulating
the electrical network.

## Records

- `ElectricalBus`: site, nominal voltage, AC/DC system, voltage basis, phase
  count, source reference, and explicit confirmation.
- `ElectricalBranch`: the two bus endpoints, site, source reference,
  confirmation, and normally-closed state.
- `AssetPortConnection`: an asset and named port connected to a bus, including
  its explicitly declared electrical interface and source reference.
- `ElectricalTopology`: the complete site-scoped collection.

AC voltage basis is explicit (line-to-line or line-to-neutral). DC uses
`voltage_basis="dc"` and no phase count. The module does not infer electrical
interfaces from an asset category, manufacturer, or model number.

## Validation behavior

The validator checks:
- unique bus, branch, connection, and asset-port identifiers;
- site consistency and valid branch endpoints;
- matching declared voltage/current-system/phase interfaces across a branch;
- matching asset-port and bus interfaces;
- explicit confirmation of buses, branches, and port connections;
- normally-connected components, with disconnected components reported as
  warnings rather than automatically treated as failures;
- assets without a declared connection, also reported as warnings.

Missing or unconfirmed topology facts block structural readiness. The report
contains machine-readable blockers, warnings, counts, and an explicit scope
label.

## Important limitations

A structurally ready topology is only a consistency check of supplied records.
It is **not** evidence of actual wiring, electrical compatibility, or safe
operation. This increment does not calculate:
- load flow, voltage drop, losses, or power flow;
- short-circuit current or protection coordination;
- grounding, arc flash, power quality, frequency stability, or transient behavior;
- transformer ratios, cable impedance, thermal ampacity, or switching interlocks.

Transformers and other voltage-changing devices are not represented as ordinary
branches. They require a future explicit component model. The current
normally-closed flag is descriptive metadata, not a switching command.

Do not connect this module to control writes. Real-site use requires qualified
site-engineering verification, calibrated device data, and a separate safety
and cybersecurity process.
