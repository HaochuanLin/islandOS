# -*- coding: utf-8 -*-
"""
Island microgrid resource co-simulation: curtailed renewables -> reverse osmosis (RO)
desalination -> upland reservoir.

Workflow
  1. Curtailment: curtail[t] = max(0, wind + PV - base load)
  2. The RO plant is driven by curtailed energy and obeys a hardware constraint:
     once started, it must run continuously for at least `min_run_hours`.
  3. Reservoir storage is accumulated dynamically:
     V[t+1] = V[t] + water produced - island water demand (clipped to capacity / minimum).
     Dispatch avoids starting/continuing a discretionary run if its known demand
     trace predicts reservoir overflow; a minimum-run commitment already in progress
     takes priority and can still spill water in exceptional cases.
  4. A four-panel figure is produced: renewable output and load, curtailment,
     RO operating state, reservoir level.

To use real data, replace load_data() with a CSV reader that returns
wind, pv, load (kW) and water_demand (m3/h) as equally long arrays.

Backup power switch `Params.allow_backup_power` (default True)
  - True : if curtailment is below the RO rated power during a forced-run hour, the
           shortfall is covered by backup power (diesel / storage) and booked in `ro_backup`.
  - False: backup power is forbidden and `ro_backup` is always 0. The start decision is
           the same mean-based test (`start_ratio`) as in the True mode. If curtailment
           cannot sustain the rated power in some hour of a running cycle, the RO plant is
           stopped immediately (emergency stop). This can violate the minimum continuous
           run constraint; check_min_run() will then report the violation.

Key assumption 1: perfect foresight
  The RO start decision reads the *actual* curtailment of the next `min_run_hours` hours,
  i.e. wind, PV and load are assumed to be known exactly in advance. A real deployment has
  to rely on weather / renewable-output / load forecasts, and forecast errors will cause
  the plant to start when curtailment later turns out to be insufficient (or to miss
  usable windows). This needs extra backup power, rolling re-planning or conservative
  margins, so the results of this prototype are optimistic.

Key assumption 2: no post-shutdown flushing
  Real RO plants normally flush the membranes with fresh water after shutdown to limit
  fouling and biological growth. This costs additional energy, water and time, and may
  constrain how soon the plant can be restarted. This prototype does not model the flushing
  step; it is an engineering simplification.
"""
from dataclasses import dataclass
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = [
    "SimHei", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
    "WenQuanYi Zen Hei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


# ----------------------------- Parameters -----------------------------
@dataclass
class Params:
    # RO system
    ro_power_kw: float = 400.0       # RO rated power (kW)
    ro_sec_kwh_m3: float = 3.5       # specific energy consumption (kWh/m3), incl. pumps, pretreatment, energy recovery
    min_run_hours: int = 2           # constraint 1: minimum continuous run time after start-up (h)
    start_ratio: float = 0.8         # start if mean curtailment over the next min_run hours >= start_ratio * rated power
    keep_ratio: float = 0.5          # after min_run, keep running while curtailment >= keep_ratio * rated power
    allow_backup_power: bool = True  # False: no backup power, stop when curtailment cannot carry the rated power
    # Upland reservoir
    res_capacity_m3: float = 3000.0  # capacity (m3)
    res_init_m3: float = 800.0       # initial storage (m3)
    res_min_m3: float = 200.0        # dead storage / safety minimum (m3)
    res_area_m2: float = 1000.0      # surface area (m2); level = volume / area
    res_base_level_m: float = 0.0    # reservoir bottom elevation / reference level (m)


# ----------------------------- Data -----------------------------
def load_data(hours: int = 24, seed: int = 42):
    """Generate example data (kW, m3/h). Return wind, pv, load, water_demand for real data."""
    rng = np.random.default_rng(seed)
    t = np.arange(hours)
    hod = t % 24

    # Wind: stronger at night plus random fluctuation, capped at 1200 kW rated
    wind = 700 + 350 * np.cos((hod - 2) / 24 * 2 * np.pi) + rng.normal(0, 60, hours)
    wind = np.clip(wind, 0, 1200)

    # PV: bell curve between 06:00 and 18:00, 1000 kW installed, with cloud disturbance
    pv = 1000 * np.clip(np.sin((hod - 6) / 12 * np.pi), 0, None)
    pv = pv * (1 - 0.15 * rng.random(hours))

    # Base load: morning and evening peaks
    load = (650 + 180 * np.exp(-((hod - 8) ** 2) / 8)
                + 260 * np.exp(-((hod - 20) ** 2) / 6)
                + rng.normal(0, 25, hours))

    # Island domestic / tourism water demand (m3/h): morning and evening peaks
    water_demand = (6 + 8 * np.exp(-((hod - 7) ** 2) / 4)
                      + 10 * np.exp(-((hod - 19) ** 2) / 5))
    return wind, pv, load, water_demand


# ----------------------------- Simulation -----------------------------
def simulate(wind, pv, load, water_demand, p: Params):
    """Run the hourly co-simulation after validating physical inputs and parameters.

    deficit[t] is the unmet water demand needed to preserve the reservoir's
    minimum reserve (dead storage); it is not a measurement of real-world service
    interruption. The hourly storage balance is:
    V[t+1] = V[t] + water_prod[t] - water_demand[t] - spill[t] + deficit[t].
    """
    named_inputs = {
        "wind": wind,
        "pv": pv,
        "load": load,
        "water_demand": water_demand,
    }
    arrays = {}
    for name, values in named_inputs.items():
        try:
            values = np.asarray(values, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a one-dimensional numeric array") from exc
        if values.ndim != 1:
            raise ValueError(f"{name} must be one-dimensional")
        if values.size == 0:
            raise ValueError("simulation inputs must contain at least one time step")
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must contain only finite values")
        if np.any(values < 0):
            raise ValueError(f"{name} must not contain negative values")
        arrays[name] = values

    lengths = {len(values) for values in arrays.values()}
    if len(lengths) != 1:
        raise ValueError("wind, pv, load, and water_demand must have equal lengths")

    def finite_numeric_parameter(name, value):
        if isinstance(value, (bool, np.bool_, str, bytes)):
            raise ValueError(f"{name} must be a finite numeric value")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a finite numeric value") from exc
        if not np.isfinite(number):
            raise ValueError(f"{name} must be finite")
        return number

    # Normalize validated numeric parameters once. Dataclass type hints are not
    # runtime checks, so reject strings/booleans instead of letting them fail
    # later with opaque NumPy/Python TypeErrors.
    ro_power_kw = finite_numeric_parameter("ro_power_kw", ro_power_kw)
    ro_sec_kwh_m3 = finite_numeric_parameter("ro_sec_kwh_m3", ro_sec_kwh_m3)
    res_capacity_m3 = finite_numeric_parameter("res_capacity_m3", res_capacity_m3)
    res_area_m2 = finite_numeric_parameter("res_area_m2", res_area_m2)
    res_min_m3 = finite_numeric_parameter("res_min_m3", res_min_m3)
    res_init_m3 = finite_numeric_parameter("res_init_m3", res_init_m3)
    res_base_level_m = finite_numeric_parameter("res_base_level_m", res_base_level_m)
    start_ratio = finite_numeric_parameter("start_ratio", start_ratio)
    keep_ratio = finite_numeric_parameter("keep_ratio", keep_ratio)

    if ro_power_kw <= 0:
        raise ValueError("ro_power_kw must be greater than zero")
    if ro_sec_kwh_m3 <= 0:
        raise ValueError("ro_sec_kwh_m3 must be greater than zero")
    if res_capacity_m3 <= 0:
        raise ValueError("res_capacity_m3 must be greater than zero")
    if res_area_m2 <= 0:
        raise ValueError("res_area_m2 must be greater than zero")
    if isinstance(p.min_run_hours, bool) or not isinstance(p.min_run_hours, (int, np.integer)) or p.min_run_hours < 1:
        raise ValueError("min_run_hours must be a positive integer")
    for name, value in (("start_ratio", start_ratio), ("keep_ratio", keep_ratio)):
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between zero and one")
    if res_min_m3 < 0:
        raise ValueError("res_min_m3 must be nonnegative")
    if not res_min_m3 <= res_init_m3 <= res_capacity_m3:
        raise ValueError("res_init_m3 must be between res_min_m3 and res_capacity_m3")
    if not isinstance(p.allow_backup_power, (bool, np.bool_)):
        raise ValueError("allow_backup_power must be a boolean")

    wind = arrays["wind"]
    pv = arrays["pv"]
    load = arrays["load"]
    water_demand = arrays["water_demand"]
    T = len(wind)
    curtail = np.maximum(0.0, wind + pv - load)          # curtailed power (kW); 1 h step -> kWh

    ro_on = np.zeros(T, dtype=int)
    ro_use = np.zeros(T)        # curtailed energy actually absorbed by RO (kWh)
    ro_backup = np.zeros(T)     # backup energy for forced-run hours with insufficient curtailment (kWh); always 0 if backup is forbidden
    water_prod = np.zeros(T)    # water produced (m3)
    spill = np.zeros(T)         # reservoir overflow (m3)
    deficit = np.zeros(T)       # unmet water demand (m3)
    emergency_stop = np.zeros(T, dtype=int)  # 1 where the safety fallback stopped RO before min_run was reached
    V = np.zeros(T + 1)         # reservoir storage; V[t] is the storage at the start of hour t
    V[0] = res_init_m3

    run_len = 0                 # consecutive hours the RO plant has been running

    def water_room_for_run(start, hours):
        """Check whether a proposed run can avoid reservoir overflow.

        This uses the known demand trace (perfect foresight). Demand is applied in
        the same hourly balance as production; inventory is kept within the
        configured dead-storage and capacity bounds.
        """
        projected = float(V[start])
        production = ro_power_kw / ro_sec_kwh_m3
        for hour in range(start, start + hours):
            projected = projected + production - water_demand[hour]
            if projected > res_capacity_m3 + 1e-9:
                return False
            projected = max(projected, res_min_m3)
        return True

    for t in range(T):
        has_water_room = water_room_for_run(t, 1)

        if run_len > 0 and run_len < p.min_run_hours:
            on = True                                   # minimum-run commitment takes priority
        elif run_len >= p.min_run_hours:
            if p.allow_backup_power:
                on = (curtail[t] >= keep_ratio * ro_power_kw) and has_water_room
            else:                                       # no backup: curtailment must carry the full rated power
                on = (curtail[t] >= ro_power_kw) and has_water_room
        else:                                           # currently stopped: look ahead to decide whether to start
            can_finish_in_horizon = (t + p.min_run_hours) <= T
            if can_finish_in_horizon and water_room_for_run(t, p.min_run_hours):
                window = curtail[t:t + p.min_run_hours]
                if p.allow_backup_power:
                    # Backup can cover weak hours, so the mean-based threshold is a
                    # dispatch heuristic rather than a guarantee of renewable-only operation.
                    on = window.mean() >= start_ratio * ro_power_kw
                else:
                    # Without backup, every hour of the minimum run must have enough
                    # curtailed power. A mean check can accept a window with one weak
                    # hour and force an impossible minimum-run violation.
                    on = bool(np.all(window >= ro_power_kw))
            else:
                on = False

        # WARNING: this emergency stop may violate the RO minimum continuous run hardware
        # constraint. It is only a safety fallback for scenarios with forecast errors. Under
        # the perfect-foresight baseline it is NOT guaranteed to stay inactive, because the
        # start test above uses the window mean, so a single weak hour inside an accepted
        # window triggers it. check_min_run() will flag such violations.
        if on and (not p.allow_backup_power) and curtail[t] < ro_power_kw:
            on = False
            if 0 < run_len < p.min_run_hours:
                emergency_stop[t] = 1

        run_len = run_len + 1 if on else 0
        ro_on[t] = int(on)

        if on:
            ro_use[t] = min(curtail[t], ro_power_kw)
            if p.allow_backup_power:
                ro_backup[t] = ro_power_kw - ro_use[t]
            water_prod[t] = ro_power_kw / ro_sec_kwh_m3   # rated flow in m3/h

        # Constraint 2: dynamic reservoir storage accumulation
        v = V[t] + water_prod[t] - water_demand[t]
        if v > res_capacity_m3:
            spill[t] = v - res_capacity_m3
            v = res_capacity_m3
        if v < res_min_m3:
            deficit[t] = res_min_m3 - v
            v = res_min_m3
        V[t + 1] = v

    level = res_base_level_m + V / res_area_m2
    return dict(curtail=curtail, ro_on=ro_on, ro_use=ro_use, ro_backup=ro_backup,
                water_prod=water_prod, spill=spill, deficit=deficit, V=V, level=level,
                emergency_stop=emergency_stop)


def check_min_run(ro_on, min_run):
    """Verify that every run segment lasts >= min_run hours (a segment cut off by the end of
    the horizon is counted as is). Return (list of segment lengths, all_ok)."""
    runs, n = [], 0
    for s in ro_on:
        if s: n += 1
        elif n: runs.append(n); n = 0
    if n: runs.append(n)
    return runs, all(r >= min_run for r in runs)


# ----------------------------- Plotting -----------------------------
def plot(wind, pv, load, res, p: Params, save_path="island_microgrid_ro.png",
         use_english_labels: bool = False):
    """Four-panel figure. use_english_labels=True -> English titles/axes/legends; False -> Chinese."""
    def L(zh, en):
        return en if use_english_labels else zh

    T = len(wind)
    h = np.arange(T)
    fig, ax = plt.subplots(4, 1, figsize=(11, 11), sharex=True,
                           gridspec_kw={"height_ratios": [3, 2, 1.2, 2.5]})

    ax[0].stackplot(h, wind, pv, labels=[L("风电", "Wind"), L("光伏", "PV")],
                    colors=["#4C9BE8", "#F5B942"], alpha=0.8)
    ax[0].plot(h, load, "k--", lw=2, label=L("基础负荷", "Base load"))
    ax[0].set_ylabel(L("功率 (kW)", "Power (kW)"))
    ax[0].set_title(L("新能源出力与基础负荷", "Renewable Output and Base Load"))
    ax[0].legend(loc="upper right", ncol=3)

    ax[1].bar(h, res["curtail"], color="#E86A5C", width=0.8, label=L("弃电量", "Curtailed energy"))
    ax[1].bar(h, res["ro_use"], color="#3FB68B", width=0.8, label=L("RO 消纳弃电", "Curtailment used by RO"))
    ax[1].set_ylabel("kWh / h")
    ax[1].set_title(L("弃电量及 RO 消纳", "Curtailment and RO Utilization"))
    ax[1].legend(loc="upper right", ncol=2)

    ax[2].step(h, res["ro_on"], where="post", color="#2A6F97", lw=2)
    ax[2].fill_between(h, res["ro_on"], step="post", alpha=0.3, color="#2A6F97")
    ax[2].set_yticks([0, 1]); ax[2].set_yticklabels([L("停机", "Off"), L("运行", "On")])
    ax[2].set_ylim(-0.1, 1.2)
    ax[2].set_title(L(f"RO 运行状态（单次最短连续运行 {p.min_run_hours} h）",
                      f"RO Operating State (min. continuous run {p.min_run_hours} h)"))

    ax[3].plot(np.arange(T + 1), res["level"], "o-", color="#1D6FA5", lw=2,
               label=L("水库水位", "Reservoir level"))
    ax[3].axhline(p.res_base_level_m + p.res_capacity_m3 / p.res_area_m2, color="r", ls=":",
                  label=L("满库水位", "Full level"))
    ax[3].axhline(p.res_base_level_m + p.res_min_m3 / p.res_area_m2, color="gray", ls=":",
                  label=L("下限水位", "Minimum level"))
    ax[3].set_ylabel(L("水位 (m)", "Level (m)"))
    ax[3].set_title(L("高地水库水位", "Upland Reservoir Level"))
    ax2 = ax[3].twinx()
    ax2.set_ylabel(L("蓄水量 (m³)", "Stored volume (m³)"))
    lo, hi = ax[3].get_ylim()
    ax2.set_ylim((lo - p.res_base_level_m) * p.res_area_m2, (hi - p.res_base_level_m) * p.res_area_m2)
    ax[3].legend(loc="upper left", ncol=3)
    ax[3].set_xlabel(L("时刻 (h)", "Hour of day (h)"))
    ax[3].set_xticks(range(0, T + 1, 2))

    for a in ax: a.grid(alpha=0.3)
    fig.suptitle(L("孤立岛屿微电网：弃电 → RO 海水淡化 → 水库 协同仿真",
                   "Island Microgrid: Curtailment → RO Desalination → Reservoir Co-simulation"),
                 fontsize=15, y=0.995)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    print(f"图已保存：{save_path}")
    plt.show()


# ----------------------------- Main -----------------------------
if __name__ == "__main__":
    ALLOW_BACKUP_POWER = True     # False: no backup power, emergency stop when curtailment is insufficient
    USE_ENGLISH_LABELS = False    # True: all figure text in English

    p = Params(allow_backup_power=ALLOW_BACKUP_POWER)
    wind, pv, load, water_demand = load_data(24)
    res = simulate(wind, pv, load, water_demand, p)

    runs, ok = check_min_run(res["ro_on"], p.min_run_hours)
    n_emerg = int(res["emergency_stop"].sum())
    print("=" * 46)
    print(f"备用电源            : {'允许' if p.allow_backup_power else '禁止（弃电不足即停机）'}")
    print(f"总弃电量            : {res['curtail'].sum():8.1f} kWh")
    print(f"RO 消纳弃电         : {res['ro_use'].sum():8.1f} kWh "
          f"({res['ro_use'].sum() / max(res['curtail'].sum(), 1e-9):.1%})")
    if p.allow_backup_power:
        print(f"备用电源补电(强制运行): {res['ro_backup'].sum():8.1f} kWh")
    else:
        print(f"备用电源补电        : 已禁用（恒为 {res['ro_backup'].sum():.1f} kWh）")
    print(f"RO 运行时长         : {res['ro_on'].sum():8d} h，运行段 {runs}，最短运行约束满足: {ok}")
    if not p.allow_backup_power:
        if n_emerg:
            print(f"[警告] 紧急提前停机 {n_emerg} 次（时刻 {np.flatnonzero(res['emergency_stop']).tolist()} h）："
                  f"已违反 RO 最短连续运行硬件约束，check_min_run 检出属预期现象")
        else:
            print("紧急提前停机        : 0 次（本次仿真未触发安全兜底）")
    print(f"总制水量            : {res['water_prod'].sum():8.1f} m³")
    print(f"水库 {res['V'][0]:.0f} -> {res['V'][-1]:.0f} m³，溢流 {res['spill'].sum():.1f} m³，缺水 {res['deficit'].sum():.1f} m³")
    print("=" * 46)
    plot(wind, pv, load, res, p, use_english_labels=USE_ENGLISH_LABELS)
