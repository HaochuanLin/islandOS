"""Application-facing view models: the structured boundary Streamlit and a future
React/TypeScript client can share.

The pages still collect inputs and render; what moves here is the *shape* of a run's
request and results. Nothing in this module calculates: it reads objects the core already
produced, validates them, and returns plain JSON-able dictionaries with stated units,
provenance and nullability.

Three contracts:

``build_run_request``
    What a page asked for. Site assumptions (from ``islandos_core.site_inputs``), the
    hourly history with its units and provenance, the page-specific settings, and the
    run-specific settings. Pages differ, so the contract carries a ``page`` discriminator
    and validates each page's own key set instead of merging them into one ambiguous
    bag.

``build_run_result_summary``
    What the run produced, limited to what the pages actually show: the recommended
    policy and its modelled 24-hour cost/unmet load (customer dashboard), or the run
    digests, decision status and service-equivalence verdict (joint optimizer). Two
    pages over the same CSV are two runs; the contract never merges their identities.

``build_annual_projection``
    The joint optimizer's declared-assumption annual projection, carrying its basis,
    the six figures, the breakdown inside the energy cost, and the definitions. It
    refuses a record that does not verify, and it never turns a 24-hour dispatch cost
    into a year by itself.

No Streamlit import, no ``st.session_state``, no page function, no global state.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

CONTRACT_VERSION = 1

PAGE_CUSTOMER_DASHBOARD = "customer_dashboard"
PAGE_JOINT_OPTIMIZER = "joint_resource_optimizer"
PAGES = (PAGE_CUSTOMER_DASHBOARD, PAGE_JOINT_OPTIMIZER)

# What each page is allowed to put in its page-specific / run-specific blocks. A key
# outside these sets is refused rather than carried through, so the contract cannot
# quietly grow a field that no page supplies.
PAGE_SETTING_KEYS = {
    PAGE_CUSTOMER_DASHBOARD: ("demand_scale", "tariff_scale", "cost_priority"),
    PAGE_JOINT_OPTIMIZER: (),
}
RUN_SETTING_KEYS = {
    PAGE_CUSTOMER_DASHBOARD: ("currency", "investment"),
    PAGE_JOINT_OPTIMIZER: ("currency", "optimizer_settings", "availability"),
}
INVESTMENT_KEYS = (
    "baseline_annual_energy_cost",
    "proposed_annual_energy_cost",
    "annual_incremental_om_cost",
    "upfront_capex",
    "project_life_years",
    "discount_rate",
    "annual_energy_saving_escalation_rate",
    "annual_om_escalation_rate",
)
OPTIMIZER_SETTING_KEYS = ("population_size", "generations", "seed")
AVAILABILITY_KEYS = ("grid_all_hours", "diesel_all_hours")


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _require_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, name)


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    return _require_bool(value, name)


def _require_page(page: object) -> str:
    if page not in PAGES:
        raise ValueError(f"page must be one of {', '.join(PAGES)}")
    return str(page)


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _check_keys(payload: Mapping[str, Any], expected: Sequence[str], name: str) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be a mapping")
    missing = [key for key in expected if key not in payload]
    extra = [key for key in payload if key not in expected]
    if missing:
        raise ValueError(f"{name} is missing {', '.join(missing)}")
    if extra:
        raise ValueError(f"{name} carries unknown fields: {', '.join(extra)}")


def _site_payload(site: object) -> dict[str, Any]:
    describe = getattr(site, "describe", None)
    digest = getattr(site, "digest", None)
    if not callable(describe) or not callable(digest):
        raise ValueError("site must be an islandos_core.site_inputs.SiteAssumptions")
    payload = dict(describe())
    if not payload:
        raise ValueError("site must describe at least one field")
    return {**payload, "digest": str(digest())}


def build_run_request(
    *,
    page: str,
    site: object,
    history: Mapping[str, Any],
    units: Mapping[str, Any],
    page_settings: Mapping[str, Any],
    run_settings: Mapping[str, Any],
    provenance: str,
    source_sha256: str | None = None,
) -> dict:
    """The request a page sent to the core, in a form another front end can replay.

    ``history`` holds canonical signal names mapped to equal-length hourly series;
    ``units`` holds the same names mapped to their unit strings. The two key sets must
    agree, or the request is refused: a series without a unit cannot be rendered safely
    by a client that does not know this repository.
    """
    page = _require_page(page)
    _check_keys(page_settings, PAGE_SETTING_KEYS[page], "page_settings")
    _check_keys(run_settings, RUN_SETTING_KEYS[page], "run_settings")
    if page == PAGE_CUSTOMER_DASHBOARD:
        _check_keys(run_settings["investment"], INVESTMENT_KEYS, "run_settings.investment")
    else:
        _check_keys(
            run_settings["optimizer_settings"], OPTIMIZER_SETTING_KEYS,
            "run_settings.optimizer_settings",
        )
        _check_keys(run_settings["availability"], AVAILABILITY_KEYS, "run_settings.availability")

    if not isinstance(history, Mapping) or not history:
        raise ValueError("history must map at least one signal to a series")
    if not isinstance(units, Mapping) or set(units) != set(history):
        raise ValueError("units must name exactly the signals in history")
    series: dict[str, list[float]] = {}
    lengths = set()
    for name, values in history.items():
        _require_text(name, "history signal name")
        _require_text(units[name], f"unit for {name}")
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError(f"history series {name} must be a sequence of numbers")
        cleaned = [_require_number(value, f"history series {name}") for value in values]
        if not cleaned:
            raise ValueError(f"history series {name} is empty")
        series[name] = cleaned
        lengths.add(len(cleaned))
    if len(lengths) != 1:
        raise ValueError("every history series must share one length")

    settings_payload = dict(page_settings)
    for name in PAGE_SETTING_KEYS[page]:
        settings_payload[name] = _require_number(settings_payload[name], name)
    run_payload = dict(run_settings)
    run_payload["currency"] = _require_text(run_payload["currency"], "run_settings.currency")
    if page == PAGE_CUSTOMER_DASHBOARD:
        investment = dict(run_payload["investment"])
        for name in INVESTMENT_KEYS:
            investment[name] = _require_number(investment[name], f"investment.{name}")
        run_payload["investment"] = investment
    else:
        optimizer = dict(run_payload["optimizer_settings"])
        for name in ("population_size", "generations", "seed"):
            optimizer[name] = _require_number(optimizer[name], f"optimizer_settings.{name}")
        run_payload["optimizer_settings"] = optimizer
        availability = dict(run_payload["availability"])
        for name in AVAILABILITY_KEYS:
            availability[name] = _require_bool(availability[name], f"availability.{name}")
        run_payload["availability"] = availability

    payload = {
        "schema_version": CONTRACT_VERSION,
        "request_type": "islandos_run_request",
        "page": page,
        "site": _site_payload(site),
        "history": {
            "signals": series,
            "units": {name: str(units[name]) for name in series},
            "hour_count": len(next(iter(series.values()))),
            "provenance": _require_text(provenance, "provenance"),
            "source_sha256": _optional_text(source_sha256, "source_sha256"),
        },
        "page_settings": settings_payload,
        "run_settings": run_payload,
    }
    payload["request_sha256"] = _digest(payload)
    return payload


def build_run_result_summary(
    *,
    page: str,
    result: Mapping[str, Any],
    economics: Mapping[str, Any] | None = None,
    planning_run: Mapping[str, Any] | None = None,
    currency: str | None = None,
) -> dict:
    """What the run produced, restricted to the fields the pages display.

    The two pages are two runs. The dashboard variant carries no run id at all, because
    its optimization run is not the run its investment screen later cites; the optimizer
    variant carries the canonical run's digests and decision status.
    """
    page = _require_page(page)
    if not isinstance(result, Mapping):
        raise ValueError("result must be the optimizer result mapping")

    if page == PAGE_CUSTOMER_DASHBOARD:
        if not isinstance(economics, Mapping):
            raise ValueError("the dashboard summary requires its service-equivalent economics")
        recommendation = result.get("recommendation")
        candidates = result.get("candidates")
        if not isinstance(recommendation, Mapping) or not isinstance(candidates, Sequence):
            raise ValueError("result is missing recommendation or candidates")
        policy = _require_text(recommendation.get("policy"), "recommendation.policy")
        by_policy = {}
        for row in candidates:
            if not isinstance(row, Mapping):
                raise ValueError("candidates must be mappings")
            by_policy[_require_text(row.get("policy"), "candidate.policy")] = row
        for needed in (policy, "grid_first"):
            if needed not in by_policy:
                raise ValueError(f"candidates do not include {needed}")
        selected = by_policy[policy].get("summary")
        baseline = by_policy["grid_first"].get("summary")
        if not isinstance(selected, Mapping) or not isinstance(baseline, Mapping):
            raise ValueError("candidate summaries must be mappings")
        service_equal = _require_bool(economics.get("service_equivalent"), "service_equivalent")
        comparable = _require_bool(
            economics.get("cost_comparison_valid"), "cost_comparison_valid"
        )
        reduction = _optional_number(
            economics.get("estimated_cost_reduction"), "estimated_cost_reduction"
        )
        payload = {
            "schema_version": CONTRACT_VERSION,
            "record_type": "islandos_run_result_summary",
            "page": page,
            "recommended_policy": policy,
            "recommended_policy_label": policy.replace("_", " ").title(),
            "estimated_24h_energy_cost": _require_number(
                selected.get("estimated_energy_cost"), "selected.estimated_energy_cost"
            ),
            "unmet_load_kwh": _require_number(selected.get("unmet_load_kwh"), "selected.unmet_load_kwh"),
            "grid_first_estimated_24h_energy_cost": _require_number(
                baseline.get("estimated_energy_cost"), "grid_first.estimated_energy_cost"
            ),
            "service_equivalent": service_equal,
            "cost_comparison_valid": comparable,
            "cost_reduction_vs_grid_first": reduction,
            "savings_claim_withheld": not (service_equal and comparable),
            "candidate_policies": sorted(by_policy),
            "run_id": None,
            "manifest_sha256": None,
            "evidence_sha256": None,
            "decision_record_status": None,
            "physical_audit_passed": None,
            "scenarios_audited": None,
            "currency": _optional_text(currency, "currency"),
        }
    else:
        if not isinstance(planning_run, Mapping):
            raise ValueError("the joint optimizer summary requires its planning run")
        recommendation = result.get("recommendation")
        if not isinstance(recommendation, Mapping):
            raise ValueError("result is missing recommendation")
        policy = recommendation.get("policy")
        economics = result.get("robust_customer_economics") or {}
        if not isinstance(economics, Mapping):
            raise ValueError("robust_customer_economics must be a mapping when present")
        decision = planning_run.get("decision_record") or {}
        if not isinstance(decision, Mapping):
            raise ValueError("decision_record must be a mapping when present")
        audit = decision.get("physical_audit") or {}
        if not isinstance(audit, Mapping):
            raise ValueError("physical_audit must be a mapping when present")
        scenarios = audit.get("scenarios_audited")
        payload = {
            "schema_version": CONTRACT_VERSION,
            "record_type": "islandos_run_result_summary",
            "page": page,
            "recommended_policy": _optional_text(policy, "recommendation.policy"),
            "recommended_policy_label": (
                policy.replace("_", " ").title()
                if isinstance(policy, str) and policy
                else "Optimizer Recommendation"
            ),
            "estimated_24h_energy_cost": None,
            "unmet_load_kwh": None,
            "grid_first_estimated_24h_energy_cost": None,
            "service_equivalent": _optional_bool(
                economics.get("service_equivalent"), "service_equivalent"
            ),
            "cost_comparison_valid": _optional_bool(
                economics.get("cost_comparison_valid"), "cost_comparison_valid"
            ),
            "cost_reduction_vs_grid_first": _optional_number(
                economics.get("estimated_cost_reduction"), "estimated_cost_reduction"
            ),
            "savings_claim_withheld": not bool(economics.get("cost_comparison_valid")),
            "candidate_policies": [],
            "run_id": _require_text(planning_run.get("run_id"), "planning_run.run_id"),
            "manifest_sha256": _require_text(
                planning_run.get("manifest_sha256"), "planning_run.manifest_sha256"
            ),
            "evidence_sha256": _require_text(
                planning_run.get("evidence_sha256"), "planning_run.evidence_sha256"
            ),
            "decision_record_status": _optional_text(decision.get("status"), "decision_record.status"),
            "physical_audit_passed": _optional_bool(audit.get("passed"), "physical_audit.passed"),
            "scenarios_audited": (
                [str(name) for name in scenarios]
                if isinstance(scenarios, Sequence) and not isinstance(scenarios, (str, bytes))
                else None
            ),
            "currency": _optional_text(currency, "currency"),
        }
    payload["summary_sha256"] = _digest(payload)
    return payload


def build_annual_projection(record: Mapping[str, Any], *, currency: str | None = None) -> dict:
    """The declared-assumption projection, or an explicit refusal.

    The record is verified here rather than trusted: a projection that does not verify
    (digest mismatch, claimed site validation, missing ``summary_source``) is refused, so
    this view can never quote a tampered or mislabelled annual figure.
    """
    from .annual_operating_basis import verify_annual_operating_basis

    if not isinstance(record, Mapping):
        raise ValueError("annual projection record must be a mapping")
    verification = verify_annual_operating_basis(record)
    if not verification["valid"]:
        raise ValueError(
            "annual projection does not verify: " + "; ".join(verification["errors"])
        )
    figures = record.get("figures")
    basis = record.get("basis")
    if not isinstance(figures, Mapping) or not isinstance(basis, Mapping):
        raise ValueError("annual projection is missing figures or basis")
    return {
        "schema_version": CONTRACT_VERSION,
        "record_type": "islandos_annual_projection_view",
        "run_id": _require_text(record.get("run_id"), "run_id"),
        "manifest_sha256": _require_text(record.get("manifest_sha256"), "manifest_sha256"),
        "data_provenance": _require_text(record.get("data_provenance"), "data_provenance"),
        "summary_source": _require_text(record.get("summary_source"), "summary_source"),
        "currency": _optional_text(currency, "currency"),
        "basis": {
            "days_equivalent_per_year": int(basis["days_equivalent_per_year"]),
            "hours_equivalent_per_year": int(basis["hours_equivalent_per_year"]),
            "equal_day_assumption": str(basis["equal_day_assumption"]),
            "derived_from_run": _require_bool(basis["derived_from_run"], "derived_from_run"),
            "site_validated": _require_bool(basis["site_validated"], "site_validated"),
            "measured": _require_bool(basis["measured"], "measured"),
            "bill": _require_bool(basis["bill"], "bill"),
        },
        "figures": {name: _require_number(figures[name], name) for name in figures},
        "components_inside_annual_energy_cost": {
            name: _require_number(value, name)
            for name, value in (record.get("components_inside_annual_energy_cost") or {}).items()
        },
        "definitions": {
            name: {"unit": str(payload["unit"]), "meaning": str(payload["meaning"])}
            for name, payload in (record.get("definitions") or {}).items()
        },
        "scope": _require_text(record.get("scope"), "scope"),
        "projection_sha256": _require_text(record.get("annualisation_sha256"), "annualisation_sha256"),
    }


def to_json(view: Mapping[str, Any]) -> str:
    """Serialise a view model, failing on anything JSON cannot carry."""
    if not isinstance(view, Mapping):
        raise ValueError("view must be a mapping")
    return json.dumps(view, sort_keys=True, allow_nan=False)
