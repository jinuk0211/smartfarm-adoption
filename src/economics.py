"""Explicit-assumption farm investment scenarios, in KRW and square metres.

RDA operating cost includes depreciation. It is deducted for an income measure
but removed from operating cost when constructing cash flow. Equipment effects
are scenario assumptions, not learned causal estimates.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _number(value: Any, name: str, minimum: float = 0) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be explicitly provided as a number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return result


def _replacements(values: Mapping[str, Any], horizon: int) -> dict[int, float]:
    result = {}
    for year, amount in values.items():
        year_int = int(year)
        if str(year_int) != str(year) or not 1 <= year_int <= horizon:
            raise ValueError("Replacement years must be whole years within the horizon")
        result[year_int] = _number(amount, "replacement cost")
    return result


def cash_flow_summary(cash_flows: list[float], discount_rate: float) -> dict[str, Any]:
    """Year-zero capital outlay plus year-end cash flows; no interpolation."""
    cumulative = 0.0
    cumulative_values = []
    payback_year = None
    for year, value in enumerate(cash_flows):
        cumulative += value
        cumulative_values.append(cumulative)
        if payback_year is None and cumulative >= 0:
            payback_year = year
    return {
        "cash_flows_krw": cash_flows,
        "cumulative_cash_flows_krw": cumulative_values,
        "payback_year": payback_year,
        "recovered_by_horizon": cumulative >= 0,
        "npv_krw": sum(value / (1 + discount_rate) ** year for year, value in enumerate(cash_flows)),
        "undiscounted_balance_krw": cumulative,
    }


def evaluate_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate new-farm or incremental retrofit economics from explicit inputs.

    Input benchmark values are per 1,000 m² and per stated period. The user must
    specify how many such periods occur per year. Retrofit initial_capex_krw is
    *additional* capital versus keeping the existing operation. Baseline annual
    cash flow is before baseline replacement investments.
    """
    benchmark = payload["benchmark"]
    period_basis = str(benchmark.get("period_basis", "")).strip()
    if not period_basis:
        raise ValueError("benchmark.period_basis is required")
    area = _number(payload.get("area_m2"), "area_m2")
    cycles = _number(payload.get("cycles_per_year"), "cycles_per_year")
    if area == 0 or cycles == 0:
        raise ValueError("area_m2 and cycles_per_year must be positive")
    capital = _number(payload.get("initial_capex_krw"), "initial_capex_krw")
    horizon_float = _number(payload.get("horizon_years"), "horizon_years", 1)
    if not horizon_float.is_integer():
        raise ValueError("horizon_years must be a whole number")
    horizon = int(horizon_float)
    rate = _number(payload.get("discount_rate", 0), "discount_rate")
    replacements = _replacements(payload.get("replacements_krw", {}), horizon)
    mode = payload.get("mode", "new")
    if mode not in {"new", "retrofit"}:
        raise ValueError("mode must be new or retrofit")
    scaling = area / 1000 * cycles
    yield_base = _number(benchmark.get("yield_kg_per_1000m2"), "benchmark yield") * scaling
    price = _number(benchmark.get("farmgate_price_krw_per_kg"), "farmgate price")
    expense = _number(benchmark.get("operating_cost_krw_per_1000m2"), "operating cost") * scaling
    depreciation = _number(benchmark.get("depreciation_krw_per_1000m2"), "depreciation") * scaling
    if depreciation > expense:
        raise ValueError("Depreciation cannot exceed operating cost containing it")
    cash_cost_base = expense - depreciation
    family_labor = benchmark.get("family_labor_cost_krw_per_1000m2")
    family_labor = None if family_labor is None else _number(family_labor, "family labor") * scaling

    baseline_cash = 0.0
    baseline_income = None
    baseline_replacements: dict[int, float] = {}
    if mode == "retrofit":
        baseline = payload.get("baseline")
        if not baseline:
            raise ValueError("Retrofit requires an explicit existing-operation baseline")
        baseline_cash = _number(baseline.get("annual_cash_flow_krw"), "baseline annual cash flow", -float("inf"))
        if baseline.get("annual_income_krw") is not None:
            baseline_income = _number(baseline["annual_income_krw"], "baseline annual income", -float("inf"))
        baseline_replacements = _replacements(baseline.get("replacements_krw", {}), horizon)

    scenarios = payload.get("scenarios")
    if not scenarios:
        raise ValueError("At least one explicitly named scenario is required")
    outputs = []
    for scenario in scenarios:
        name = str(scenario.get("name", "")).strip()
        if not name:
            raise ValueError("Each scenario needs a name")
        yield_multiplier = _number(scenario.get("yield_multiplier"), "yield_multiplier")
        price_multiplier = _number(scenario.get("price_multiplier"), "price_multiplier")
        cost_multiplier = _number(scenario.get("cash_cost_multiplier"), "cash_cost_multiplier")
        quantity = yield_base * yield_multiplier
        scenario_price = price * price_multiplier
        revenue = quantity * scenario_price
        cash_cost = cash_cost_base * cost_multiplier
        cash_surplus = revenue - cash_cost
        income = cash_surplus - depreciation
        incremental_cash = cash_surplus - baseline_cash
        flows = [-capital] + [
            incremental_cash - replacements.get(year, 0) + baseline_replacements.get(year, 0)
            for year in range(1, horizon + 1)
        ]
        summary = cash_flow_summary(flows, rate)
        future_value = sum(flows[1:])
        discounted_future = sum(flows[year] / (1 + rate) ** year for year in range(1, horizon + 1))
        annual_repayment_requirement = (
            capital + sum(replacements.values()) - sum(baseline_replacements.values())
        ) / horizon
        required_revenue = cash_cost + baseline_cash + annual_repayment_requirement
        required_quantity = None if scenario_price == 0 else max(0, required_revenue / scenario_price)
        outputs.append({
            "name": name,
            "assumptions": dict(scenario),
            "annual_yield_kg": quantity,
            "farmgate_price_krw_per_kg": scenario_price,
            "annual_revenue_krw": revenue,
            "annual_cash_operating_cost_krw": cash_cost,
            "annual_depreciation_krw": depreciation,
            "annual_income_before_family_labor_krw": income,
            "annual_family_labor_opportunity_cost_krw": family_labor,
            "annual_income_after_family_labor_krw": None if family_labor is None else income - family_labor,
            "annual_cash_surplus_before_replacements_krw": cash_surplus,
            "annual_incremental_cash_flow_before_replacements_krw": incremental_cash,
            "annual_incremental_income_krw": None if baseline_income is None else income - baseline_income,
            "maximum_capex_for_horizon_payback_krw": None if future_value < 0 else future_value,
            "maximum_capex_for_nonnegative_npv_krw": None if discounted_future < 0 else discounted_future,
            "required_annual_yield_for_horizon_payback_kg": required_quantity,
            "additional_yield_required_kg": None if required_quantity is None else max(0, required_quantity - quantity),
            **summary,
        })
    return {
        "mode": mode,
        "area_m2": area,
        "period_basis": period_basis,
        "cycles_per_year": cycles,
        "initial_capex_krw": capital,
        "horizon_years": horizon,
        "discount_rate": rate,
        "scenarios": outputs,
        "interpretation": "Assumption scenarios, not confidence intervals or causal equipment effects",
        "exclusions": ["tax", "financing cash flows", "grants", "working-capital changes", "terminal resale value"],
        "cost_note": "Operating cost includes depreciation; cash cost excludes it. Family labor is a separate opportunity cost.",
    }
