# Simulation-only autonomous flexible-load gate

This prototype moves IslandOS one step closer to an autonomous decision loop: it
consumes a row from the rolling-horizon dispatcher and evaluates an independent
set of fail-closed gates before emitting a simulated `ON`, `OFF`, or `HOLD`
decision.

## Run the tests

```bash
python -m pytest -q tests/test_simulated_autonomous_flex_load_gate.py
```

## Decision gates

The gate rejects an action when telemetry is invalid, plant interlocks are not
healthy, an operator stop is active, the requested total power exceeds the
configured power envelope, the requested load exceeds the reported surplus, or
the dispatch row reports constraint violations. Invalid/missing numeric fields
are rejected rather than guessed. Every result carries a stable reason code and
explicit `physical_write_performed: false` and `live_control_enabled: false`
fields.

The defaults are illustrative software-test values, not engineering limits for
any particular island or plant. The caller must supply trustworthy gate status;
this module does not itself establish sensor authenticity, evaluate real PLC
interlocks, or independently verify a device's safe state.

## What this is — and is not

- It is a deterministic, auditable policy gate for simulated autonomous decisions.
- It is not an LLM, machine-learning model, production controller, or safety
  certification.
- It does not connect to hardware, publish MQTT commands, write to PLCs, or
  actuate equipment.
- It does not prove site safety or real-world benefits. Before any live use,
  integrate an authenticated read-only telemetry path, validate site-specific
  limits and interlocks, test failure behavior, and complete independent
  operational and safety review.

IslandOS's machine-learning experiments, rolling-horizon scheduler, this gate,
and any future LLM should remain separate components. A language model may help
interpret goals or explain evidence, but it must not bypass the deterministic
constraints or issue unrestricted actuator commands.
