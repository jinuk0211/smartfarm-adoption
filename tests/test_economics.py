import pytest

from src.economics import evaluate_plan


def plan():
    return {
        "benchmark": {
            "yield_kg_per_1000m2": 1000,
            "farmgate_price_krw_per_kg": 10,
            "operating_cost_krw_per_1000m2": 6000,
            "depreciation_krw_per_1000m2": 2000,
            "family_labor_cost_krw_per_1000m2": 1000,
            "period_basis": "1기작",
        },
        "area_m2": 2000,
        "cycles_per_year": 1,
        "initial_capex_krw": 30000,
        "horizon_years": 5,
        "discount_rate": 0,
        "scenarios": [{"name": "명시적 가정", "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1}],
    }


def test_area_scaling_and_depreciation_not_double_deducted():
    result = evaluate_plan(plan())["scenarios"][0]
    assert result["annual_yield_kg"] == 2000
    assert result["annual_cash_operating_cost_krw"] == 8000
    assert result["annual_income_before_family_labor_krw"] == 8000
    assert result["annual_income_after_family_labor_krw"] == 6000
    assert result["cash_flows_krw"] == [-30000, 12000, 12000, 12000, 12000, 12000]
    assert result["payback_year"] == 3


def test_no_recovery_and_zero_price_no_division_error():
    payload = plan()
    payload["scenarios"][0]["price_multiplier"] = 0
    result = evaluate_plan(payload)["scenarios"][0]
    assert result["payback_year"] is None
    assert not result["recovered_by_horizon"]
    assert result["required_annual_yield_for_horizon_payback_kg"] is None
    assert result["maximum_capex_for_nonnegative_npv_krw"] is None


def test_retrofit_is_incremental_and_replacements_are_differences():
    payload = plan()
    payload.update(mode="retrofit", baseline={"annual_cash_flow_krw": 10000, "annual_income_krw": 7000, "replacements_krw": {"2": 1000}}, replacements_krw={"2": 4000})
    result = evaluate_plan(payload)["scenarios"][0]
    assert result["annual_incremental_cash_flow_before_replacements_krw"] == 2000
    assert result["cash_flows_krw"] == [-30000, 2000, -1000, 2000, 2000, 2000]
    assert result["annual_incremental_income_krw"] == 1000
    assert result["payback_year"] is None
    assert result["additional_yield_required_kg"] == 460


def test_missing_quote_is_not_silently_zero():
    payload = plan()
    del payload["initial_capex_krw"]
    with pytest.raises(ValueError, match="initial_capex"):
        evaluate_plan(payload)


def test_retrofit_requires_actual_baseline():
    payload = plan()
    payload["mode"] = "retrofit"
    with pytest.raises(ValueError, match="baseline"):
        evaluate_plan(payload)


def test_period_is_explicit_and_costs_consistent():
    payload = plan()
    payload["benchmark"]["depreciation_krw_per_1000m2"] = 7000
    with pytest.raises(ValueError, match="Depreciation"):
        evaluate_plan(payload)


def test_discount_and_replacement_at_correct_year():
    payload = plan()
    payload.update(discount_rate=0.1, replacements_krw={"5": 1000})
    result = evaluate_plan(payload)["scenarios"][0]
    expected = -30000 + sum(12000 / 1.1**year for year in range(1, 6)) - 1000 / 1.1**5
    assert result["npv_krw"] == pytest.approx(expected)
