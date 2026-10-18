from copy import deepcopy

import pytest

from src.farm_economics import COST_CATEGORIES, evaluate_facility_plan


def facility_plan():
    target = {
        "plan_id": "TEST_PLAN", "facility_id": "TEST_FACILITY", "crop": "딸기",
        "area_m2": 1000, "cycle_start": "2026-09-01", "cycle_end": "2027-05-31",
        "financial_start": "2026-09-01", "financial_end": "2027-08-31",
        "variety": "설향", "region": "경북", "district": "고령", "facility_type": "비닐온실",
    }
    evidence = {
        "scope": deepcopy(target),
        "source_kind": "budget", "source_ref": "자동 테스트의 가상 계획이며 실자료가 아님",
    }
    costs = []
    for category in COST_CATEGORIES:
        amount = {"seedlings": 1000, "energy_water": 1000, "hired_labor": 1000,
                  "packaging_transport": 1, "depreciation": 2000, "family_labor": 1000}.get(category, 0)
        costs.append({**deepcopy(evidence), "category": category, "amount_krw": amount,
                      "basis": "per_kg" if category == "packaging_transport" else "annual_total"})
    return {
        "target": target, "evidence_target": deepcopy(target), "mode": "new",
        "prediction": {"status": "predicted", "target": "shipment", "unit": "kg", "prediction": 1000,
                       "query": {"crop": "딸기", "area_m2": 1000, "planting_year": 2026, "planting_month": 9,
                                 "variety": "설향", "region": "경북", "district": "고령", "facility_type": "비닐온실"},
                       "target_period_confirmed": False, "warnings": ["future_year_not_prospectively_validated"]},
        "acknowledge_prediction_period": True, "repeat_annual_plan": True,
        "sales": [{**deepcopy(evidence), "label": "가상 계약", "share": 1,
                   "net_price_krw_per_kg": 10, "sale_start": "2026-12-01", "sale_end": "2027-05-31"}],
        "costs": costs,
        "investments": [{**deepcopy(evidence), "label": "가상 설치견적", "amount_krw": 6000,
                         "coverage": "테스트용 전체 설치 가정, 실제 견적 아님"}],
        "investment_scope_confirmed": True, "horizon_years": 5, "discount_rate": 0,
        "replacements_krw": {},
        "scenarios": [
            {"name": "불리", "yield_multiplier": .5, "price_multiplier": 1, "cash_cost_multiplier": 1},
            {"name": "기준", "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1},
        ],
    }


def base_result(payload):
    return next(row for row in evaluate_facility_plan(payload)["scenarios"] if row["name"] == "기준")


def test_itemized_costs_prices_and_capital_connect_to_one_target_without_benchmark():
    payload = facility_plan()
    result = evaluate_facility_plan(payload)
    base = next(row for row in result["scenarios"] if row["name"] == "기준")
    assert base["annual_revenue_krw"] == 10000
    assert base["annual_cash_operating_cost_krw"] == 4000
    assert base["annual_income_after_family_labor_krw"] == 3000
    assert base["cash_flows_krw"] == [-6000, 6000, 6000, 6000, 6000, 6000]
    assert base["payback_year"] == 1
    assert result["target_context"] == payload["target"]
    assert result["evidence_summary"]["external_reference_used"] is False
    assert result["quality"]["income_accuracy_validated"] is False


def test_sales_mix_weights_prices_instead_of_using_one_unrelated_average():
    payload = facility_plan()
    first = payload["sales"][0]
    first.update(share=.75, net_price_krw_per_kg=10)
    payload["sales"].append({**deepcopy(first), "label": "다른 판매채널", "share": .25, "net_price_krw_per_kg": 20})
    assert base_result(payload)["annual_revenue_krw"] == 12500


def test_variable_packaging_cost_changes_with_yield_and_break_even_includes_it():
    result = evaluate_facility_plan(facility_plan())
    downside = next(row for row in result["scenarios"] if row["name"] == "불리")
    assert downside["annual_cash_operating_cost_krw"] == 3500
    assert downside["payback_year"] == 4
    assert downside["required_annual_yield_for_horizon_payback_kg"] == pytest.approx((3000 + 6000 / 5) / 9)
    assert downside["operating_break_even_yield_kg"] == pytest.approx(3000 / 9)


@pytest.mark.parametrize("field,value", [("facility_id", "OTHER"), ("area_m2", 2000),
                                        ("crop", "토마토"), ("cycle_end", "2027-06-01")])
def test_bound_evidence_cannot_silently_follow_changed_target(field, value):
    payload = facility_plan()
    payload["target"][field] = value
    with pytest.raises(ValueError, match="변경"):
        evaluate_facility_plan(payload)


@pytest.mark.parametrize("section", ["sales", "costs", "investments"])
def test_single_foreign_facility_or_period_line_is_rejected(section):
    payload = facility_plan()
    payload[section][0]["scope"]["facility_id"] = "OTHER"
    with pytest.raises(ValueError, match="시설 또는 연간 적용기간"):
        evaluate_facility_plan(payload)
    payload = facility_plan()
    payload[section][0]["scope"]["financial_start"] = "2025-09-01"
    with pytest.raises(ValueError, match="시설 또는 연간 적용기간"):
        evaluate_facility_plan(payload)


def test_missing_expense_is_not_zero_and_all_categories_are_required():
    payload = facility_plan()
    payload["costs"][0]["amount_krw"] = None
    with pytest.raises(ValueError, match="미입력"):
        evaluate_facility_plan(payload)
    payload["costs"][0]["amount_krw"] = 0
    assert base_result(payload)["annual_cash_operating_cost_krw"] == 3000
    payload["costs"].pop()
    with pytest.raises(ValueError, match="필수 비용항목"):
        evaluate_facility_plan(payload)


def test_reference_and_user_declared_quote_are_never_promoted_to_verified_records():
    payload = facility_plan()
    payload["costs"][0]["source_kind"] = "external_reference"
    payload["investments"][0]["source_kind"] = "quote"
    result = evaluate_facility_plan(payload)
    assert result["evidence_summary"]["external_reference_used"] is True
    assert not any(row["document_verified"] for row in result["evidence_ledger"])
    assert result["quality"]["equipment_effect_validated"] is False


def test_retrofit_uses_same_target_baseline_and_incremental_cash_not_whole_revenue():
    payload = facility_plan()
    evidence = {name: deepcopy(payload["sales"][0][name]) for name in ("scope", "source_kind", "source_ref")}
    payload.update(mode="retrofit", baseline={
        **evidence, "yield_kg": 800, "sales": deepcopy(payload["sales"]),
        "costs": deepcopy(payload["costs"]), "replacements_krw": {"2": 100},
    }, replacements_krw={"2": 400})
    base = base_result(payload)
    assert base["annual_incremental_cash_flow_before_replacements_krw"] == 1800
    assert base["cash_flows_krw"] == [-6000, 1800, 1500, 1800, 1800, 1800]
    assert base["payback_year"] == 4
    payload["baseline"]["scope"]["facility_id"] = "ANOTHER_FARM"
    with pytest.raises(ValueError, match="시설 또는 연간 적용기간"):
        evaluate_facility_plan(payload)


@pytest.mark.parametrize("change,error", [
    (lambda p: p["sales"][0].update(share=.9), "100%"),
    (lambda p: p["sales"][0].update(sale_end="2027-06-01"), "판매기간"),
    (lambda p: p["prediction"]["query"].update(area_m2=2000), "예측 품목·면적"),
    (lambda p: p["prediction"]["query"].update(planting_month=10), "정식 연월"),
    (lambda p: p.update(repeat_annual_plan=False), "여러 해"),
    (lambda p: p.update(acknowledge_prediction_period=False), "작기 완결"),
    (lambda p: p.update(replacements_krw=None), "교체비 계획"),
    (lambda p: p["costs"][0].update(source_ref=""), "출처·계산근거"),
    (lambda p: p["costs"].append(deepcopy(p["costs"][0])), "중복 비용항목"),
])
def test_invalid_linkages_or_unstated_assumptions_are_rejected(change, error):
    payload = facility_plan()
    change(payload)
    with pytest.raises(ValueError, match=error):
        evaluate_facility_plan(payload)


def test_zero_price_or_zero_quantity_has_no_infinite_or_false_break_even():
    payload = facility_plan()
    payload["sales"][0]["net_price_krw_per_kg"] = 0
    base = base_result(payload)
    assert base["payback_year"] is None
    assert base["required_annual_yield_for_horizon_payback_kg"] is None
    payload["prediction"]["prediction"] = 0
    assert base_result(payload)["full_cost_break_even_price_krw_per_kg"] is None


def test_numeric_missingness_and_nonfinite_inputs_rejected():
    for value in (None, True, float("nan"), float("inf"), -1):
        payload = facility_plan()
        payload["investments"][0]["amount_krw"] = value
        with pytest.raises(ValueError):
            evaluate_facility_plan(payload)


def test_evaluation_does_not_modify_inputs():
    payload = facility_plan()
    before = deepcopy(payload)
    evaluate_facility_plan(payload)
    assert payload == before


@pytest.mark.parametrize("field,value", [("area_m2", 2000), ("crop", "토마토"),
                                        ("cycle_start", "2026-10-01"), ("variety", "다른품종")])
def test_each_evidence_row_retains_its_own_area_crop_cycle_and_variety(field, value):
    payload = facility_plan()
    payload["costs"][0]["scope"][field] = value
    with pytest.raises(ValueError, match="계획과 다릅니다"):
        evaluate_facility_plan(payload)


def test_real_saved_shipment_model_connects_without_unit_relabeling():
    from pathlib import Path
    from src.planning_models import load_planning_models, predict_plan

    project = Path(__file__).resolve().parents[1]
    bundle = load_planning_models(project)["shipment"]
    payload = facility_plan()
    query = dict(bundle["example_query"], area_m2=1000, planting_year=2026, planting_month=9)
    for name in ("variety", "region", "district", "facility_type"):
        payload["target"][name] = query[name]
    payload["evidence_target"] = deepcopy(payload["target"])
    for section in ("sales", "costs", "investments"):
        for row in payload[section]:
            row["scope"] = deepcopy(payload["target"])
    prediction = predict_plan(bundle, query)
    assert prediction["unit"] == "kg_per_recorded_cycle"
    payload["prediction"] = prediction
    result = evaluate_facility_plan(payload)
    assert result["model_connection"]["prediction"] == prediction
    assert base_result(payload)["annual_yield_kg"] == pytest.approx(prediction["prediction"])
