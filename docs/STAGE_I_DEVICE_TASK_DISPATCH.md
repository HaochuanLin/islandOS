# Stage I — device tasks in shared energy accounting

The Stage H scheduler produces per-device power profiles. This adapter maps
those profiles into the existing IslandOS EnergySystemInputs contract:

- Critical task demand is added to base load and to the critical-load subset.
- Semi-flexible and fully-flexible demand is added to the separate flexible
  load channel, preserving the energy engine's independent shed accounting.
- The shared energy engine then evaluates PV, wind, battery, grid and diesel
  against the combined demand using its existing chronological physical balance.

The task scheduler's available-power budget must be calculated after other
fixed site loads; this avoids allocating the same capacity twice. The adapter
does not infer missing assets, grid availability, tariffs or site constraints.

This closes the software hand-off between device-level tasks and the shared
energy balance. It does not turn the heuristic scheduler into a global
multi-resource optimizer, nor does it establish site savings or control
authorization. Forecast uncertainty, equipment derating and outage stress
remain separate validation requirements.
