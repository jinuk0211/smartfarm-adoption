import pytest

from src.economics import evaluate_plan
from src.risk_simulation import OUTPUTS, simulate_plan


def plan():
    return {"benchmark": {"yield_kg_per_1000m2": 1000, "farmgate_price_krw_per_kg": 10,
                           "operating_cost_krw_per_1000m2": 6000, "depreciation_krw_per_1000m2": 2000,
                           "family_labor_cost_krw_per_1000m2": 1000, "period_basis": "1 year"},
            "area_m2": 2000, "cycles_per_year": 1, "initial_capex_krw": 30000,
            "horizon_years": 5, "discount_rate": .05, "replacements_krw": {"3": 2000},
            "scenarios": [{"name": "base", "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1}]}


@pytest.mark.parametrize("retrofit", [False, True])
def test_zero_uncertainty_is_exactly_the_economic_calculator(retrofit):
    payload = plan()
    if retrofit:
        payload.update(mode="retrofit", baseline={"annual_cash_flow_krw": 10000, "replacements_krw": {"2": 500}})
    direct = evaluate_plan(payload)["scenarios"][0]
    result = simulate_plan(payload, {"yield": 0, "price": 0, "cash_cost": 0}, n_samples=5)
    assert result["deterministic"] == direct
    for sample in result["samples"]:
        for key in OUTPUTS + ["payback_year"]:
            assert sample[key] == direct[key]
    assert result["quantiles"]["npv_krw"] == {"p05": direct["npv_krw"], "p50": direct["npv_krw"], "p95": direct["npv_krw"]}


def test_reproducible_assumptions_not_probability_claims():
    assumptions = {"yield": .2, "price": .2, "cash_cost": .1}
    first = simulate_plan(plan(), assumptions, n_samples=200, seed=7)
    assert first == simulate_plan(plan(), assumptions, n_samples=200, seed=7)
    assert first["samples"] != simulate_plan(plan(), assumptions, n_samples=200, seed=8)["samples"]
    assert "NOT calibrated" in first["assumptions"]["interpretation"]
    for sample in first["samples"]:
        assert 1600 <= sample["annual_yield_kg"] <= 2400
        assert 7200 <= sample["annual_cash_operating_cost_krw"] <= 8800


def test_undefined_price_bep_remains_missing_and_family_labor_not_invented():
    payload = plan()
    payload["scenarios"][0]["price_multiplier"] = 0
    del payload["benchmark"]["family_labor_cost_krw_per_1000m2"]
    result = simulate_plan(payload, {"yield": 0, "price": 0, "cash_cost": 0}, n_samples=1)
    assert result["quantiles"]["required_annual_yield_for_horizon_payback_kg"] is None
    assert result["quantiles"]["annual_income_after_family_labor_krw"] is None
    assert result["samples"][0]["payback_year"] is None


@pytest.mark.parametrize("widths", [{"yield": .2}, {"yield": -.1, "price": 0, "cash_cost": 0}, {"yield": float("nan"), "price": 0, "cash_cost": 0}])
def test_invalid_or_incomplete_uncertainty_is_rejected(widths):
    with pytest.raises(ValueError):
        simulate_plan(plan(), widths)
