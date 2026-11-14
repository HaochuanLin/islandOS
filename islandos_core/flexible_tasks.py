"""Equipment-aware scheduling for critical and shiftable electrical tasks."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Sequence

LoadClass = Literal["critical", "semi_flexible", "fully_flexible"]

@dataclass(frozen=True)
class DeviceTask:
    task_id: str
    name: str
    load_class: LoadClass
    rated_power_kw: float
    required_energy_kwh: float
    earliest_start_step: int
    latest_finish_step: int
    min_power_kw: float = 0.0
    minimum_run_steps: int = 1
    interruptible: bool = True
    priority: int = 100
    availability: tuple[bool, ...] | None = None
    critical_power_profile_kw: tuple[float, ...] | None = None

@dataclass(frozen=True)
class DeviceTaskSchedule:
    task_id: str
    name: str
    load_class: LoadClass
    power_kw: tuple[float, ...]
    energy_kwh: float
    energy_requirement_kwh: float
    operating_steps: tuple[int, ...]
    energy_cost: float

@dataclass(frozen=True)
class DeviceSchedulingResult:
    schedules: tuple[DeviceTaskSchedule, ...]
    critical_power_kw: tuple[float, ...]
    total_power_kw: tuple[float, ...]
    residual_power_kw: tuple[float, ...]
    total_energy_kwh: float
    total_energy_cost: float
    dt_hours: float
    method: str = "priority_then_lowest_tariff_feasible_placement"
    def to_dict(self) -> dict:
        return {
            "schedules": [{"task_id": x.task_id, "name": x.name, "load_class": x.load_class,
                "power_kw": list(x.power_kw), "energy_kwh": x.energy_kwh,
                "energy_requirement_kwh": x.energy_requirement_kwh,
                "operating_steps": list(x.operating_steps), "energy_cost": x.energy_cost}
                for x in self.schedules],
            "critical_power_kw": list(self.critical_power_kw),
            "total_power_kw": list(self.total_power_kw),
            "residual_power_kw": list(self.residual_power_kw),
            "total_energy_kwh": self.total_energy_kwh,
            "total_energy_cost": self.total_energy_cost,
            "dt_hours": self.dt_hours, "method": self.method,
        }

def _series(values: Sequence[float], name: str) -> list[float]:
    result = list(values)
    if not result:
        raise ValueError(f"{name} must be non-empty")
    for value in result:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not float("-inf") < float(value) < float("inf"):
            raise ValueError(f"{name} must contain finite numeric values")
    return [float(x) for x in result]

def _validate_task(task: DeviceTask, horizon: int) -> None:
    if not task.task_id.strip() or not task.name.strip():
        raise ValueError("task_id and name must be non-empty")
    if task.load_class not in ("critical", "semi_flexible", "fully_flexible"):
        raise ValueError(f"unsupported load_class: {task.load_class}")
    if isinstance(task.rated_power_kw, bool) or not isinstance(task.rated_power_kw, (int, float)) or not 0 < task.rated_power_kw < float("inf"):
        raise ValueError("rated_power_kw must be finite and positive")
    if isinstance(task.min_power_kw, bool) or not isinstance(task.min_power_kw, (int, float)) or not 0 <= task.min_power_kw <= task.rated_power_kw:
        raise ValueError("min_power_kw must be between zero and rated_power_kw")
    if isinstance(task.required_energy_kwh, bool) or not isinstance(task.required_energy_kwh, (int, float)) or not 0 <= task.required_energy_kwh < float("inf"):
        raise ValueError("required_energy_kwh must be finite and non-negative")
    if (isinstance(task.earliest_start_step, bool) or not isinstance(task.earliest_start_step, int)
        or isinstance(task.latest_finish_step, bool) or not isinstance(task.latest_finish_step, int)
        or not 0 <= task.earliest_start_step < task.latest_finish_step <= horizon):
        raise ValueError("task operating window must satisfy 0 <= earliest < latest <= horizon")
    if isinstance(task.minimum_run_steps, bool) or not isinstance(task.minimum_run_steps, int) or task.minimum_run_steps < 1:
        raise ValueError("minimum_run_steps must be an integer >= 1")
    if not isinstance(task.interruptible, bool) or isinstance(task.priority, bool) or not isinstance(task.priority, int):
        raise ValueError("interruptible must be boolean and priority must be integer")
    if task.availability is not None and (len(task.availability) != horizon or any(type(x) is not bool for x in task.availability)):
        raise ValueError("availability must be a horizon-length boolean tuple")
    if task.load_class == "critical":
        if task.critical_power_profile_kw is None or len(task.critical_power_profile_kw) != horizon:
            raise ValueError("critical tasks require a horizon-length critical_power_profile_kw")
        if task.availability is not None:
            raise ValueError("critical tasks use their fixed profile, not an availability mask")
        for p in task.critical_power_profile_kw:
            if (isinstance(p, bool) or not isinstance(p, (int, float))
                or not 0 <= p <= task.rated_power_kw or not float("-inf") < float(p) < float("inf")):
                raise ValueError("critical profile power must be finite and between zero and rated_power_kw")
            if 0 < p < task.min_power_kw:
                raise ValueError("critical profile power must be zero or at least min_power_kw")
        if any(task.critical_power_profile_kw[t] > 0 for t in range(horizon)
               if not task.earliest_start_step <= t < task.latest_finish_step):
            raise ValueError("critical profile cannot consume power outside its operating window")
    elif task.critical_power_profile_kw is not None:
        raise ValueError("only critical tasks may define critical_power_profile_kw")
    elif task.required_energy_kwh > 0 and task.minimum_run_steps > task.latest_finish_step - task.earliest_start_step:
        raise ValueError("minimum_run_steps exceeds operating window")
    if task.load_class == "fully_flexible" and task.interruptible and task.minimum_run_steps != 1:
        raise ValueError("interruptible tasks currently require minimum_run_steps=1; use non-interruptible for contiguous runs")

def schedule_device_tasks(tasks: Sequence[DeviceTask], price_per_kwh: Sequence[float],
                          available_power_kw: Sequence[float], dt_hours: float = 1.0) -> DeviceSchedulingResult:
    """Reserve critical profiles; then schedule flexible tasks without shedding service.

    This first version uses rated power for whole intervals. Required energy must
    be an integer multiple of rated_power_kw * dt_hours.
    """
    prices, capacity = _series(price_per_kwh, "price_per_kwh"), _series(available_power_kw, "available_power_kw")
    horizon = len(prices)
    if len(capacity) != horizon:
        raise ValueError("available_power_kw must match price horizon")
    if any(x < 0 for x in capacity):
        raise ValueError("available_power_kw must be non-negative")
    if isinstance(dt_hours, bool) or not isinstance(dt_hours, (int, float)) or not 0 < dt_hours < float("inf"):
        raise ValueError("dt_hours must be finite and positive")
    if any(not isinstance(x, DeviceTask) for x in tasks):
        raise ValueError("tasks must contain DeviceTask instances")
    ids = [x.task_id for x in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task_id values must be unique")
    for task in tasks:
        _validate_task(task, horizon)

    critical, remaining, results = [0.0] * horizon, list(capacity), []
    for task in tasks:
        if task.load_class != "critical":
            continue
        profile = [float(x) for x in task.critical_power_profile_kw]
        energy = sum(profile) * dt_hours
        if abs(energy - task.required_energy_kwh) > max(1e-8, task.required_energy_kwh * 1e-9):
            raise ValueError(f"critical task {task.task_id} profile energy mismatch")
        for t, p in enumerate(profile):
            if p > remaining[t] + 1e-9:
                raise ValueError(f"critical load capacity violation at step {t}: {task.task_id}")
            critical[t] += p
            remaining[t] -= p
        results.append(DeviceTaskSchedule(task.task_id, task.name, task.load_class, tuple(profile),
            energy, task.required_energy_kwh, tuple(i for i,p in enumerate(profile) if p > 0),
            sum(prices[i] * profile[i] * dt_hours for i in range(horizon))))

    flexible = sorted((x for x in tasks if x.load_class != "critical"),
        key=lambda x: (x.priority, 0 if x.load_class == "semi_flexible" else 1, x.task_id))
    for task in flexible:
        quantum = task.rated_power_kw * dt_hours
        raw = task.required_energy_kwh / quantum
        count = round(raw)
        if abs(raw - count) > 1e-8:
            raise ValueError(f"task {task.task_id} energy must be an integer multiple of rated_power_kw * dt_hours")
        if count == 0:
            results.append(DeviceTaskSchedule(task.task_id, task.name, task.load_class,
                tuple([0.0]*horizon), 0.0, 0.0, (), 0.0))
            continue
        eligible = [t for t in range(task.earliest_start_step, task.latest_finish_step)
            if task.availability is None or task.availability[t]]
        if task.load_class == "semi_flexible" or not task.interruptible:
            if count < task.minimum_run_steps:
                raise ValueError(f"task {task.task_id} cannot satisfy minimum_run_steps")
            candidates = []
            for start in eligible:
                block = list(range(start, start + count))
                if (block[-1] < task.latest_finish_step
                    and all(task.availability is None or task.availability[t] for t in block)
                    and all(remaining[t] >= task.rated_power_kw - 1e-9 for t in block)):
                    cost = sum(prices[t] * task.rated_power_kw * dt_hours for t in block)
                    candidates.append((cost, start, block))
            if not candidates:
                raise ValueError(f"task {task.task_id} infeasible within operating window and power budget")
            selected = min(candidates, key=lambda x: (x[0], x[1]))[2]
        else:
            ranked = sorted((t for t in eligible if remaining[t] >= task.rated_power_kw - 1e-9),
                key=lambda t: (prices[t], t))
            if len(ranked) < count:
                raise ValueError(f"task {task.task_id} infeasible within operating window and power budget")
            selected = sorted(ranked[:count])
        profile = [0.0] * horizon
        for t in selected:
            profile[t] = task.rated_power_kw
            remaining[t] -= task.rated_power_kw
        energy = sum(profile) * dt_hours
        results.append(DeviceTaskSchedule(task.task_id, task.name, task.load_class, tuple(profile),
            energy, task.required_energy_kwh, tuple(selected),
            sum(prices[t] * profile[t] * dt_hours for t in selected)))

    total = [critical[t] + sum(x.power_kw[t] for x in results if x.load_class != "critical") for t in range(horizon)]
    residual = [capacity[t] - total[t] for t in range(horizon)]
    return DeviceSchedulingResult(tuple(results), tuple(critical), tuple(total), tuple(residual),
        sum(x.energy_kwh for x in results), sum(x.energy_cost for x in results), float(dt_hours))
