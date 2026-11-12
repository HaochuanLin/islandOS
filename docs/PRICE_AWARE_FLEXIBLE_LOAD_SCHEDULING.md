# Price-aware flexible-load scheduling

## Why this module exists

SIC_backend demonstrates a demand-response pattern: move deferrable electrical
consumption toward lower-price periods while respecting a power budget. IslandOS
has its own flexible-load simulation and multi-objective dispatch experiments;
this module adds a separate, reusable price-aware scheduling primitive rather
than replacing those systems or importing third-party source code.

## Current model

The new optimizer solves a continuous linear program:

- Decision variable: electrical power assigned to each time interval (kW).
- Objective: minimize the sum of price times power times interval duration.
- Hard energy requirement: deliver the requested total energy (kWh).
- Per-interval bound: power cannot exceed the lower of the load rating and the
  power budget available after essential demand / higher-priority reservations.
- Operating window: optional boolean mask disables unavailable intervals.
- Optional baseline profile: compares the optimized cost with a baseline that
  delivers the same total energy and respects the load rating and operating
  window. The baseline may use more grid power than the flexible renewable
  budget, which is useful when comparing grid-heavy and renewable-aware plans.

The function raises an explicit infeasibility error when the requested energy
cannot fit in the allowed horizon. It does not silently reduce required service.

## Example

    from optimization.price_aware_load_optimizer import optimize_flexible_load

    schedule = optimize_flexible_load(
        price_per_kwh=[0.30, 0.10, 0.20, 0.08],
        energy_requirement_kwh=6.0,
        max_power_kw=2.0,
        available_power_kw=[2.0, 2.0, 1.0, 2.0],
    )
    print(schedule.to_dict())

## Important limitations

This first version is appropriate only for continuous, deferrable loads whose
energy requirement can be shifted within the selected horizon. It does not
model minimum on/off duration, startup costs, ramp rates, discrete operating
states, thermal/process dynamics, network power flow, or equipment protection.
Those require a separately specified MILP or physical process model.

The result is a candidate schedule under supplied prices and constraints. It
does not establish customer savings, site feasibility, forecast accuracy, or
permission to control equipment. It must be compared with the site's actual
baseline and reviewed by a responsible operator.

## Relationship to the wider IslandOS optimizer

This module is complementary to dispatch_engine.py and the NSGA-II / schedule
screening experiments. It solves a narrow tariff-aware load-shifting problem;
it is not a replacement for common-physics evaluation, multi-resource
coordination, or hard service-reliability checks.


## Reproducible demo

Run the example from the repository root:

    python examples/price_aware_flexible_load_demo.py

The example compares a fixed illustrative baseline schedule with the optimized
schedule under the same synthetic tariff and the same total energy requirement.
It prints both costs and their difference. This difference is a mathematical
scenario comparison only, not measured savings, a customer quote, or a forecast
of future savings. Replace all inputs with validated site data before using the
calculation in a customer business case.

## Validation coverage

The unit tests cover cheapest-period allocation, per-interval power budgets,
operating windows, non-hourly intervals, infeasible requirements, zero-energy
requests, negative prices, malformed inputs, reproducibility, equal-energy
baseline comparisons, invalid baseline rejection, and energy/cost accounting.
