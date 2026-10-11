"""Behavioral checks for validated farm forecasts and their financial bridge."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from src.planning_models import (
    FEATURES, apply_prediction_to_plan, fit_candidate,
    predict_portable, export_portable, predict_plan, load_planning_models, digest, dsz_prediction_for_plan,
)
from src.economics import evaluate_plan


def example_rows():
    return pd.DataFrame([
        {"crop": "딸기", "variety": "설향", "region": "경북", "district": "고령",
         "facility_type": "연동", "planting_year": 2021, "planting_month": 9,
         "area_m2": 1000 + i * 200, "target": (1000 + i * 200) * (3 + i / 10),
         "group": f"farm{i}", "record_id": f"row{i}"}
        for i in range(12)
    ])


def financial_plan():
    return {"area_m2": 2000, "cycles_per_year": 1, "initial_capex_krw": 100000,
            "horizon_years": 2, "discount_rate": 0, "mode": "new",
            "benchmark": {"period_basis": "년1기작/10a", "yield_kg_per_1000m2": 3000,
                          "farmgate_price_krw_per_kg": 1000,
                          "operating_cost_krw_per_1000m2": 1000000,
                          "depreciation_krw_per_1000m2": 100000,
                          "family_labor_cost_krw_per_1000m2": 200000},
            "scenarios": [{"name": "기준", "yield_multiplier": 1,
                           "price_multiplier": 1, "cash_cost_multiplier": 1}]}


@pytest.mark.parametrize("method", ["crop_area_median", "catboost_log_density", "xgboost_log_density"])
def test_portable_model_matches_fitted_model_and_uses_area(method):
    rows = example_rows()
    candidate = fit_candidate(rows, method)
    portable = export_portable(candidate)
    queries = rows[FEATURES].iloc[[1, 8]].copy()
    actual = candidate.predict(queries)
    expected = predict_portable(portable, queries)
    np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=1e-3)
    queries.loc[:, "area_m2"] *= 2
    assert np.isfinite(predict_portable(portable, queries)).all()
    assert "farm0" not in str(portable)


def test_unseen_crop_does_not_get_other_crops_median():
    rows = example_rows()
    candidate = fit_candidate(rows, "crop_area_median")
    portable = export_portable(candidate)
    bundle = {"portable": portable, "target": "shipment", "unit": "kg_per_recorded_cycle",
              "support": {"crops": ["딸기"], "area_min_m2": 1000, "area_max_m2": 3200,
                          "categories": {name: rows[name].unique().tolist()
                                         for name in FEATURES if name not in ["planting_year", "planting_month", "area_m2"]}}}
    query = rows[FEATURES].iloc[0].to_dict()
    query["crop"] = "토마토"
    assert predict_plan(bundle, query)["status"] == "unsupported_crop"


@pytest.mark.parametrize("method", ["catboost_log_density", "xgboost_log_density"])
def test_portable_split_border_rounding_matches_native_float32(method):
    rows = example_rows()
    candidate = fit_candidate(rows, method)
    portable = export_portable(candidate)
    offset = sum(len(values) for values in portable["categories"])
    borders = []
    for tree in portable["trees"]:
        if method == "catboost_log_density":
            borders.extend((split["feature"] - offset, split["border"])
                           for split in tree["splits"] if split["feature"] >= offset)
        else:
            borders.extend((feature - offset, border) for left, feature, border in
                           zip(tree["left_children"], tree["split_indices"], tree["split_conditions"])
                           if left != -1 and feature >= offset)
    queries = []
    for feature, border in borders[:20]:
        if feature == 2:
            for epsilon in [-1e-8, 0, 1e-8]:
                query = rows[FEATURES].iloc[0].to_dict()
                query["area_m2"] = border + epsilon
                queries.append(query)
    assert queries
    frame = pd.DataFrame(queries)
    np.testing.assert_allclose(candidate.predict(frame), predict_portable(portable, frame), rtol=2e-6, atol=.01)


def test_bridge_requires_explicit_period_and_keeps_annual_costs():
    plan = financial_plan()
    prediction = {"status": "predicted", "target": "shipment", "prediction": 8000,
                  "unit": "kg_per_recorded_cycle", "query": {"area_m2": 2000},
                  "model": "catboost_log_density"}
    with pytest.raises(ValueError, match="period"):
        apply_prediction_to_plan(plan, prediction, acknowledge_period=False)
    bridged = apply_prediction_to_plan(plan, prediction, acknowledge_period=True)
    result = evaluate_plan(bridged)["scenarios"][0]
    assert result["annual_yield_kg"] == 8000
    assert result["annual_revenue_krw"] == 8000000
    assert result["annual_cash_operating_cost_krw"] == 1800000
    assert result["annual_income_after_family_labor_krw"] == 5600000
    assert plan == financial_plan()


def test_revenue_model_is_not_scaled_twice_or_priced_again():
    plan = financial_plan()
    prediction = {"status": "predicted", "target": "revenue", "prediction": 10000000,
                  "unit": "krw_per_recorded_cycle", "query": {"area_m2": 2000},
                  "model": "xgboost_log_density"}
    bridged = apply_prediction_to_plan(plan, prediction, acknowledge_period=True)
    bridged["scenarios"].append({"name": "불리", "yield_multiplier": .9,
                                "price_multiplier": .8, "cash_cost_multiplier": 1.1})
    results = evaluate_plan(bridged)["scenarios"]
    assert results[0]["annual_revenue_krw"] == 10000000
    assert results[1]["annual_revenue_krw"] == pytest.approx(7200000)
    assert results[0]["revenue_basis"] == "recorded_cycle_revenue_model"
    assert results[0]["farmgate_price_krw_per_kg"] == pytest.approx(10000000 / 6000)


def test_switching_revenue_to_shipment_clears_prior_revenue_override():
    prediction = {"status": "predicted", "target": "revenue", "prediction": 10000000,
                  "unit": "krw_per_recorded_cycle", "query": {"area_m2": 2000},
                  "model": "crop_area_median"}
    plan = apply_prediction_to_plan(financial_plan(), prediction, acknowledge_period=True)
    prediction.update(target="shipment", unit="kg_per_recorded_cycle", prediction=8000)
    plan = apply_prediction_to_plan(plan, prediction, acknowledge_period=True)
    result = evaluate_plan(plan)["scenarios"][0]
    assert result["annual_revenue_krw"] == 8000000
    assert result["revenue_basis"] == "quantity_times_farmgate_price"


@pytest.mark.parametrize("field,value", [("prediction", -1), ("prediction", float("nan")),
                                        ("unit", "grams"), ("status", "unsupported_crop")])
def test_bridge_rejects_invalid_predictions(field, value):
    prediction = {"status": "predicted", "target": "shipment", "prediction": 8000,
                  "unit": "kg_per_recorded_cycle", "query": {"area_m2": 2000},
                  "model": "crop_area_median"}
    prediction[field] = value
    with pytest.raises(ValueError):
        apply_prediction_to_plan(financial_plan(), prediction, acknowledge_period=True)


def test_bridge_rejects_area_mismatch_and_extra_cycles():
    prediction = {"status": "predicted", "target": "shipment", "prediction": 8000,
                  "unit": "kg_per_recorded_cycle", "query": {"area_m2": 1000},
                  "model": "crop_area_median"}
    with pytest.raises(ValueError, match="area"):
        apply_prediction_to_plan(financial_plan(), prediction, acknowledge_period=True)
    prediction["query"]["area_m2"] = 2000
    plan = deepcopy(financial_plan())
    plan["cycles_per_year"] = 2
    with pytest.raises(ValueError, match="annual"):
        apply_prediction_to_plan(plan, prediction, acknowledge_period=True)


def test_model_loader_rejects_stale_model_or_changed_verified_code(tmp_path):
    import json
    reports = tmp_path / "reports"
    reports.mkdir()
    models = reports / "planning_models.json"
    models.write_text(json.dumps({"models": {"shipment": {"verified": True}}}), encoding="utf-8")
    code = tmp_path / "verified.py"
    code.write_text("verified = True", encoding="utf-8")
    summary = reports / "planning_validation_summary.json"
    summary.write_text(json.dumps({"models_sha256": digest(models), "code_sha256": {"verified.py": digest(code)}}), encoding="utf-8")
    assert load_planning_models(tmp_path)["shipment"]["verified"]
    code.write_text("verified = False", encoding="utf-8")
    with pytest.raises(ValueError, match="code"):
        load_planning_models(tmp_path)
    code.write_text("verified = True", encoding="utf-8")
    models.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_planning_models(tmp_path)


def test_dsz_bridge_keeps_synthetic_origin_visible_in_financial_result():
    row = {"target": "shipment", "unit": "kg", "prediction": 8000,
           "data_kind": "synthetic_schema_fixture", "selected_cpu_model": "catboost",
           "source_manifest_sha256": "fixture-hash", "target_assumption": "single_record_per_cycle"}
    prediction = dsz_prediction_for_plan(row, {"area_m2": 2000, "crop": "딸기"})
    connected = apply_prediction_to_plan(financial_plan(), prediction, acknowledge_period=True)
    result = evaluate_plan(connected)
    assert result["model_connection"]["prediction"]["data_kind"] == "synthetic_schema_fixture"
    assert result["model_connection"]["prediction"]["target_period_confirmed"] is False
    assert result["scenarios"][0]["annual_yield_kg"] == 8000
    row["unit"] = "grams"
    with pytest.raises(ValueError, match="unit"):
        dsz_prediction_for_plan(row, {"area_m2": 2000, "crop": "딸기"})
