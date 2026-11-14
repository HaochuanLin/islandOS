# Stage H — equipment-aware flexible-load tasks

This module extends the existing RO/ice-storage plug-ins and continuous tariff
LP; it does not replace them.

- Critical loads use a fixed power profile. They are reserved first. Any site
  capacity conflict is a hard error, never silent critical-load shedding.
- Semi-flexible loads run as a contiguous block within their start/finish window.
- Fully flexible interruptible loads may be split across eligible intervals.
- Each task records identity, load class, rated power, required energy, earliest
  start, latest finish (exclusive), minimum run steps, interruptibility,
  priority and optional availability mask.

The first scheduler runs at rated power for whole intervals. Required energy
must be an integer multiple of rated_power_kw times dt_hours. This explicit
restriction avoids inventing partial-load behavior. Lower numeric priority
values are scheduled first; within a task, the scheduler chooses the least-cost
feasible placement. Infeasible tasks reject the whole plan rather than being
silently dropped or energy-shortened.

This is a deterministic tariff-aware heuristic, not a global optimizer or
plant controller. It does not model startup costs, ramping, minimum off-time,
partial-load curves, process dynamics, network constraints or equipment
interlocks. Field deployment still requires site engineering and operator
approval.

Run: pytest -q tests/test_device_flexible_tasks.py tests/test_flexible_loads.py tests/test_price_aware_load_optimizer.py

Tests cover critical-load protection, priority, contiguous and interruptible
scheduling, time windows, power bounds, infeasibility and energy accounting.
Synthetic/unit-test evidence is not field validation.
