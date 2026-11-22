"""Surface the annual-economics citation above every number on the customer page.

`INTEGRATION.md` §6.3 makes the annual figures a citation, not a derivation: the
customer types the bills, and the run only supplies the equipment and service
scope those bills are read against. A page that prints NPV first and admits
"customer-entered" in a small caption underneath has inverted the reading order,
because a reader who stops at the number never learns it was not produced here.

This module owns that ordering in one place, the same way
`decision_record_panel` owns the audit gate on the schedule page: the basis goes
above the metrics, and a binding that does not verify stops the page instead of
falling back to showing bare numbers.
"""

from __future__ import annotations

from typing import Mapping

import streamlit as st

from islandos_core.investment_economics import verify_investment_economics_binding

RECORD_TYPE = "investment_economics_run_binding"
DEMONSTRATION_SOURCE = "synthetic_demonstration_figures"
CUSTOMER_SOURCE = "customer_entered_annual_bills"
_DEFAULT_ANNUALISATION = (
    "customer-entered annual bills tied to this run's equipment and service scope; "
    "this screen never turns a simulated day into the bills it screens"
)
_NOT_PROVEN = (
    "not the run's savings, not measured from the run, and not a procurement guarantee"
)
_NOT_PROVEN_DEMO = (
    "synthetic demonstration figures for showing how the screen works, not a customer "
    "quote, a market price, a measured saving, or a site-validated return"
)

# The example the dashboard pre-fills so a first-time reader sees a complete screen.
# Chosen to produce one screen-positive case (NPV ≈ +21k, payback ≈ 6 years at the
# page's 10-year/8% defaults) so the decision wording is legible; they are not a
# quote for any site.
DEMONSTRATION_VALUES = {
    "baseline_annual_bill": 120_000.0,
    "proposed_annual_bill": 84_000.0,
    "annual_incremental_om": 6_000.0,
    "upfront_capex": 180_000.0,
}


def _require(binding: object) -> Mapping:
    if not isinstance(binding, Mapping):
        raise ValueError("annual economics binding must be a mapping")
    if binding.get("record_type") != RECORD_TYPE:
        raise ValueError(
            "annual economics binding is missing or is not an investment economics run binding"
        )
    return binding


def binding_errors(binding: object) -> list[str]:
    """Integrity errors for the binding; empty means it may be quoted."""
    if not isinstance(binding, Mapping):
        return ["annual economics binding is not a mapping"]
    return list(verify_investment_economics_binding(binding).get("errors") or [])


def annual_inputs_supplied(
    *,
    baseline_annual_bill: float,
    proposed_annual_bill: float,
    upfront_capex: float,
) -> bool:
    """True only when the customer has supplied the figures this screen judges.

    Both bills and the CAPEX field default to zero, and a zero is exactly what an
    unfilled field looks like. Running the screen on those placeholders produces a
    confident-looking "negative" verdict that describes nothing the customer said,
    so the page asks this first and withholds every metric until a real baseline
    bill and a real CAPEX quote exist. A zero *proposed* bill is allowed: an
    off-grid site can legitimately claim it.
    """
    for name, value in (
        ("baseline_annual_bill", baseline_annual_bill),
        ("proposed_annual_bill", proposed_annual_bill),
        ("upfront_capex", upfront_capex),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    return float(baseline_annual_bill) > 0 and float(upfront_capex) > 0


def annual_source_for(
    *,
    baseline_annual_bill: float,
    proposed_annual_bill: float,
    annual_incremental_om: float,
    upfront_capex: float,
) -> str:
    """The provenance string for the annual figures a page is about to bind.

    A page that pre-fills its own example numbers so a first-time reader sees a
    complete screen must not let those numbers pass as customer data. Values that
    still equal the page's demonstration set are labelled synthetic; anything the
    customer changed is labelled customer-entered.
    """
    demo = DEMONSTRATION_VALUES
    unchanged = (
        float(baseline_annual_bill) == demo["baseline_annual_bill"]
        and float(proposed_annual_bill) == demo["proposed_annual_bill"]
        and float(annual_incremental_om) == demo["annual_incremental_om"]
        and float(upfront_capex) == demo["upfront_capex"]
    )
    return DEMONSTRATION_SOURCE if unchanged else CUSTOMER_SOURCE


def basis_level(binding: Mapping) -> str:
    """Streamlit severity for the basis banner: 'warning' when withheld, else 'info'."""
    return "warning" if _require(binding).get("withheld") is True else "info"


def source_of(binding: Mapping) -> str:
    """The provenance string the binding recorded for the annual figures."""
    basis = _require(binding).get("annual_basis")
    if not isinstance(basis, Mapping):
        basis = {}
    return str(basis.get("source") or CUSTOMER_SOURCE)


def is_demonstration(binding: Mapping) -> bool:
    """True when the annual figures are the page's own synthetic example values."""
    return source_of(binding) == DEMONSTRATION_SOURCE


def annual_basis_text(binding: Mapping) -> str:
    """One sentence saying where the annual numbers came from."""
    basis = _require(binding).get("annual_basis")
    if not isinstance(basis, Mapping):
        basis = {}
    source = source_of(binding)
    if source == DEMONSTRATION_SOURCE:
        text = (
            "Illustrative screening results: the annual bills, incremental O&M and CAPEX "
            f"are {_NOT_PROVEN_DEMO} (source: {source})"
        )
    else:
        text = f"Annual bills are entered by the customer ({source}), so they are {_NOT_PROVEN}"
    period = basis.get("period_utc")
    if isinstance(period, (list, tuple)) and len(period) == 2:
        text += f"; the stated billing period is {period[0]} to {period[1]}"
    return text + "."


def withheld_text(binding: Mapping) -> str:
    """Say plainly whether any metric below is being withheld, and why."""
    record = _require(binding)
    if record.get("withheld") is True:
        return (
            "Withheld: service equivalence to the grid-first reference is not proven "
            "for this run, so no investment metric is quoted."
        )
    return (
        "Withheld: no - metrics below are shown because the service-equivalence gate "
        "passed for this run."
    )


def binding_facts(binding: Mapping) -> list[tuple[str, str]]:
    """The facts that must appear before the first metric, in reading order."""
    record = _require(binding)
    basis = record.get("annual_basis")
    if not isinstance(basis, Mapping):
        basis = {}
    manifest = str(record.get("manifest_sha256") or "")
    digest = str(record.get("binding_sha256") or "")
    annualisation = str(basis.get("annualisation") or _DEFAULT_ANNUALISATION).rstrip(".")
    demo = source_of(record) == DEMONSTRATION_SOURCE
    return [
        ("Run", str(record.get("run_id") or "missing")),
        (
            "Bills / O&M / CAPEX",
            "synthetic demonstration values entered on this page" if demo
            else "entered by the customer, not computed here",
        ),
        ("Derived from this run", "no - the annual bills were entered, not computed here"),
        ("Withheld", "yes" if record.get("withheld") is True else "no"),
        ("Annualisation", annualisation),
        ("Manifest SHA-256", f"{manifest[:8]}…" if manifest else "missing"),
        ("Binding SHA-256", f"{digest[:8]}…" if digest else "missing"),
    ]


def render_annual_economics_basis(binding: Mapping) -> None:
    """Render the basis banner and facts; stop the page if the binding is broken."""
    errors = binding_errors(binding)
    if errors:
        st.error(
            "Annual economics binding does not verify: "
            + "; ".join(errors)
            + ". No investment metric is shown for this run."
        )
        st.stop()
    facts = binding_facts(binding)
    banner = f"{annual_basis_text(binding)} {withheld_text(binding)}"
    if basis_level(binding) == "warning":
        st.warning(banner)
    else:
        st.info(banner)
    st.caption(" · ".join(f"**{label}:** {value}" for label, value in facts))
