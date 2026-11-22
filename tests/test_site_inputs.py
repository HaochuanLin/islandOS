"""One site vocabulary, three pages, and no number that moved.

The refactor this file guards only changed *where* site assumptions become an
`EnergySystemConfig`. Everything else — the ten fields, their defaults, their units, the
fact that the device planner describes a smaller demo site — has to stay exactly as it
was. So the tests here do four things:

1. pin the recorded baseline values, field by field, so a "harmless cleanup" that nudges
   40 kW to 42 kW fails;
2. compare the new construction against the literal config each page used to build,
   field by field, instead of comparing one hash and calling it done;
3. prove the module is Streamlit-free and that pages no longer assemble configs
   themselves;
4. prove illegal or missing inputs are refused instead of silently defaulted.
"""

from pathlib import Path
import subprocess
import sys

import pytest

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.site_inputs import (
    BATTERY_INITIAL_SOC,
    BATTERY_MAX_SOC,
    BATTERY_MIN_SOC,
    DEFAULT_SITE,
    DEVICE_PLANNER_DEMO_SITE,
    SITE_FIELDS,
    SiteAssumptions,
    default_site,
    device_planner_demo_site,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_05 = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
PAGE_06 = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"
PAGE_09 = REPO_ROOT / "pages" / "09_Device_Flexibility_Planner.py"

# The values the dashboard and the joint optimizer shipped before this refactor, taken
# from pages/05 (~line 191) and pages/06 (~line 119). Nothing may move them.
RECORDED_DASHBOARD_DEFAULTS = {
    "pv_rated_kw": 40.0,
    "wind_rated_kw": 20.0,
    "grid_import_limit_kw": 100.0,
    "battery_capacity_kwh": 80.0,
    "battery_power_kw": 20.0,
    "battery_initial_soc": 0.60,
    "battery_min_soc": 0.10,
    "battery_max_soc": 0.95,
    "diesel_rated_kw": 0.0,
    "diesel_variable_cost_per_kwh": 0.0,
}

# The device planner's literals, from pages/09 before this refactor (two identical
# configs at ~line 110 and ~line 134). A smaller site on purpose.
RECORDED_PLANNER_SITE = {
    "pv_rated_kw": 12.0,
    "wind_rated_kw": 4.5,
    "grid_import_limit_kw": 20.0,
    "battery_capacity_kwh": 12.0,
    "battery_power_kw": 4.0,
    "battery_initial_soc": 0.60,
    "battery_min_soc": 0.10,
    "battery_max_soc": 0.95,
    "diesel_rated_kw": 5.0,
    "diesel_variable_cost_per_kwh": 0.35,
}

UNIT_AND_TYPE = {
    "pv_rated_kw": ("kW", float),
    "wind_rated_kw": ("kW", float),
    "grid_import_limit_kw": ("kW", float),
    "battery_capacity_kwh": ("kWh", float),
    "battery_power_kw": ("kW", float),
    "battery_initial_soc": ("fraction of capacity", float),
    "battery_min_soc": ("fraction of capacity", float),
    "battery_max_soc": ("fraction of capacity", float),
    "diesel_rated_kw": ("kW", float),
    "diesel_variable_cost_per_kwh": ("currency / kWh", float),
}


def test_the_shared_vocabulary_contains_only_site_fields():
    assert set(SITE_FIELDS) == set(RECORDED_DASHBOARD_DEFAULTS)
    # Page-specific and run-specific names must never enter this set.
    for forbidden in (
        "cost_priority", "demand_scale", "tariff_scale", "population", "generations",
        "seed", "project_life_years", "discount_rate", "upfront_capex",
        "baseline_annual_bill", "grid_available", "diesel_available", "currency",
    ):
        assert forbidden not in SITE_FIELDS


def test_the_dashboard_and_joint_optimizer_defaults_are_byte_for_byte_unchanged():
    assert DEFAULT_SITE == RECORDED_DASHBOARD_DEFAULTS
    assert default_site().describe() == RECORDED_DASHBOARD_DEFAULTS


def test_the_device_planners_site_is_declared_and_not_merged_into_the_default():
    assert DEVICE_PLANNER_DEMO_SITE == RECORDED_PLANNER_SITE
    assert device_planner_demo_site().describe() == RECORDED_PLANNER_SITE
    # Different site, so different digest: the difference is data, not drift.
    assert default_site().digest() != device_planner_demo_site().digest()


@pytest.mark.parametrize("field", SITE_FIELDS)
def test_every_field_keeps_its_unit_type_and_default(field):
    unit, kind = UNIT_AND_TYPE[field]
    value = DEFAULT_SITE[field]
    assert isinstance(value, kind), f"{field} is {type(value)}, not {kind}"
    assert isinstance(unit, str) and unit
    # The attribute carries the same value and the same type as the declared default.
    assert getattr(default_site(), field) == value
    assert isinstance(getattr(default_site(), field), kind)


def _dashboard_config_before_this_refactor() -> EnergySystemConfig:
    """The exact literal config pages/05 built before the refactor."""
    return EnergySystemConfig(
        pv_rated_kw=40.0,
        wind_rated_kw=20.0,
        grid_import_limit_kw=100.0,
        battery=BatterySpec(
            capacity_kwh=80.0,
            max_charge_kw=20.0,
            max_discharge_kw=20.0,
            initial_soc=0.60,
            min_soc=0.10,
            max_soc=0.95,
        ),
    )


def _joint_optimizer_config_before_this_refactor() -> EnergySystemConfig:
    """The exact literal config pages/06 built before the refactor."""
    return EnergySystemConfig(
        pv_rated_kw=40.0,
        wind_rated_kw=20.0,
        grid_import_limit_kw=100.0,
        battery=BatterySpec(
            capacity_kwh=80.0,
            max_charge_kw=20.0,
            max_discharge_kw=20.0,
            initial_soc=0.60,
            min_soc=0.10,
            max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=30.0,
            variable_cost_per_kwh=0.32,
            ramp_up_kw_per_hour=30.0,
        ),
    )


def _planner_config_before_this_refactor() -> EnergySystemConfig:
    """The exact literal config pages/09 built before the refactor (both replays)."""
    return EnergySystemConfig(
        pv_rated_kw=12.0,
        wind_rated_kw=4.5,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=12.0, max_charge_kw=4.0, max_discharge_kw=4.0,
            initial_soc=0.60, min_soc=0.10, max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=5.0, variable_cost_per_kwh=0.35, ramp_up_kw_per_hour=5.0,
        ),
    )


def test_the_dashboard_site_builds_the_config_it_built_before():
    assert default_site().to_energy_system_config() == _dashboard_config_before_this_refactor()


def test_the_joint_optimizer_site_builds_the_config_it_built_before():
    assumptions = default_site().with_overrides(
        diesel_rated_kw=30.0, diesel_variable_cost_per_kwh=0.32,
    )
    assert assumptions.to_energy_system_config() == _joint_optimizer_config_before_this_refactor()


def test_the_device_planner_site_builds_the_config_it_built_before():
    assert device_planner_demo_site().to_energy_system_config() == _planner_config_before_this_refactor()


def test_a_shared_change_reaches_every_page_from_one_place():
    changed = default_site().with_overrides(pv_rated_kw=60.0)
    # Every page builds its config from the same object, so one edit is one edit.
    assert changed.to_energy_system_config().pv_rated_kw == 60.0
    assert changed.describe()["pv_rated_kw"] == 60.0
    assert changed.digest() != default_site().digest()


@pytest.mark.parametrize("field", SITE_FIELDS)
def test_every_shared_field_is_inside_the_digest(field):
    replacement = {
        "pv_rated_kw": 41.0,
        "wind_rated_kw": 21.0,
        "grid_import_limit_kw": 101.0,
        "battery_capacity_kwh": 81.0,
        "battery_power_kw": 21.0,
        "battery_initial_soc": 0.55,
        "battery_min_soc": 0.05,
        "battery_max_soc": 0.90,
        "diesel_rated_kw": 1.0,
        "diesel_variable_cost_per_kwh": 0.01,
    }[field]
    assert default_site().with_overrides(**{field: replacement}).digest() != default_site().digest()


@pytest.mark.parametrize("field", SITE_FIELDS)
def test_no_field_may_be_omitted_or_defaulted(field):
    payload = dict(RECORDED_DASHBOARD_DEFAULTS)
    payload.pop(field)
    with pytest.raises(TypeError, match=field):
        SiteAssumptions(**payload)


@pytest.mark.parametrize(
    "field, value",
    [
        ("pv_rated_kw", -1.0),
        ("pv_rated_kw", float("nan")),
        ("pv_rated_kw", float("inf")),
        ("pv_rated_kw", True),
        ("pv_rated_kw", "40"),
        ("pv_rated_kw", None),
        ("battery_max_soc", 1.2),
    ],
)
def test_illegal_site_values_are_refused_instead_of_defaulted(field, value):
    payload = dict(RECORDED_DASHBOARD_DEFAULTS)
    payload[field] = value
    # The message names the offending field (either by its full name or by the SOC
    # bound it breaks), so a caller can tell which input was refused.
    expected = "max_soc" if field == "battery_max_soc" else field
    with pytest.raises(ValueError, match=expected):
        SiteAssumptions(**payload)


def test_state_of_charge_bounds_are_enforced():
    with pytest.raises(ValueError, match="min_soc < max_soc"):
        SiteAssumptions(**{**RECORDED_DASHBOARD_DEFAULTS, "battery_min_soc": 0.95, "battery_max_soc": 0.10})
    with pytest.raises(ValueError, match="battery_initial_soc"):
        SiteAssumptions(**{**RECORDED_DASHBOARD_DEFAULTS, "battery_initial_soc": 0.99})


def test_no_battery_and_no_diesel_are_absent_devices_not_zero_sized_devices():
    absent = SiteAssumptions(**{
        **RECORDED_DASHBOARD_DEFAULTS,
        "battery_capacity_kwh": 0.0,
        "battery_power_kw": 0.0,
    })
    assert absent.battery_spec() is None
    assert absent.to_energy_system_config().battery is None
    # Same rule pages/05 applied: a battery needs both capacity and power.
    half = SiteAssumptions(**{**RECORDED_DASHBOARD_DEFAULTS, "battery_power_kw": 0.0})
    assert half.battery_spec() is None
    assert default_site().diesel_spec() is None
    assert default_site().to_energy_system_config().diesel is None


def test_overrides_refuse_a_field_that_is_not_a_site_field():
    with pytest.raises(ValueError, match="unknown site fields"):
        default_site().with_overrides(cost_priority=0.7)


def test_the_module_never_imports_streamlit():
    source = (REPO_ROOT / "islandos_core" / "site_inputs.py").read_text(encoding="utf-8")
    # The docstring may mention Streamlit; the import list may not.
    assert "import streamlit" not in source
    assert "from streamlit" not in source
    assert "session_state" not in source
    completed = subprocess.run(
        [sys.executable, "-c",
         "import sys; import islandos_core.site_inputs as m; "
         "assert 'streamlit' not in sys.modules; print(m.default_site().digest()[:8])"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_the_pages_no_longer_construct_configs_themselves():
    for page in (PAGE_05, PAGE_06, PAGE_09):
        source = page.read_text(encoding="utf-8")
        assert "EnergySystemConfig(" not in source, f"{page.name} still builds a config"
        assert "BatterySpec(" not in source, f"{page.name} still builds a battery"
        assert "DieselSpec(" not in source, f"{page.name} still builds a diesel"
    assert "SiteAssumptions(" in PAGE_05.read_text(encoding="utf-8")
    assert ".to_energy_system_config()" in PAGE_05.read_text(encoding="utf-8")
    assert "SiteAssumptions(" in PAGE_06.read_text(encoding="utf-8")
    assert ".to_energy_system_config()" in PAGE_06.read_text(encoding="utf-8")
    assert "device_planner_demo_site()" in PAGE_09.read_text(encoding="utf-8")
    assert ".to_energy_system_config()" in PAGE_09.read_text(encoding="utf-8")


def test_page_specific_settings_survive_the_unification():
    page_05 = PAGE_05.read_text(encoding="utf-8")
    page_06 = PAGE_06.read_text(encoding="utf-8")
    page_09 = PAGE_09.read_text(encoding="utf-8")
    # The dashboard's own simulation knobs and investment inputs stay on its page.
    for name in ("demand_scale", "tariff_scale", "cost_priority", "project_life", "upfront_capex"):
        assert name in page_05, f"{name} disappeared from the dashboard"
    # The optimizer's search knobs stay on its page.
    for name in ("population", "generations", "seed"):
        assert name in page_06, f"{name} disappeared from the joint optimizer"
    # The planner's tasks and price vector stay on its page.
    for name in ("schedule_device_tasks", "task_power_budget"):
        assert name in page_09, f"{name} disappeared from the planner"


def test_soc_constants_are_the_ones_every_page_passes():
    assert (BATTERY_INITIAL_SOC, BATTERY_MIN_SOC, BATTERY_MAX_SOC) == (0.60, 0.10, 0.95)
    for page in (PAGE_05, PAGE_06):
        source = page.read_text(encoding="utf-8")
        assert "battery_initial_soc=BATTERY_INITIAL_SOC" in source
        assert "battery_min_soc=BATTERY_MIN_SOC" in source
        assert "battery_max_soc=BATTERY_MAX_SOC" in source
