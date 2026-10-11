"""A matching plan ID must not bypass the exact original DSZ input provenance."""

import json

import pandas as pd
import pytest

from scripts.connect_dsz_economics import connect_files
from src.planning_models import digest


def files(tmp_path):
    plans = tmp_path / "plans.csv"
    predictions = tmp_path / "predictions.csv"
    pd.DataFrame([{"plan_id": "a", "crop": "딸기", "area_m2": 1000}]).to_csv(plans, index=False)
    pd.DataFrame([{"plan_id": "a", "target": "shipment", "prediction": 4000, "unit": "kg",
                   "data_kind": "synthetic_schema_fixture", "selected_cpu_model": "xgboost",
                   "source_manifest_sha256": "fixture", "target_assumption": "single_record_per_cycle"}]).to_csv(predictions, index=False)
    predictions.with_suffix(".provenance.json").write_text(json.dumps({
        "prediction_sha256": digest(predictions), "plans_sha256": digest(plans), "rows": 1}), encoding="utf-8")
    costs = {"a": {"area_m2": 1000, "cycles_per_year": 1, "initial_capex_krw": 100000,
                    "horizon_years": 2, "discount_rate": 0, "reference": {"crop": "딸기"},
                    "benchmark": {"period_basis": "annual", "yield_kg_per_1000m2": 3000,
                                  "farmgate_price_krw_per_kg": 1000, "operating_cost_krw_per_1000m2": 1000000,
                                  "depreciation_krw_per_1000m2": 100000, "family_labor_cost_krw_per_1000m2": 0},
                    "scenarios": [{"name": "base", "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1}]}}
    return predictions, plans, costs


def test_verified_dsz_prediction_connects_and_carries_provenance(tmp_path):
    predictions, plans, costs = files(tmp_path)
    results = connect_files(predictions, plans, costs, assume_one_cycle=True)
    assert results[0]["results"]["scenarios"][0]["annual_yield_kg"] == 4000
    assert results[0]["data_kind"] == "synthetic_schema_fixture"
    assert results[0]["prediction_inputs_provenance"]["plans_sha256"] == digest(plans)


def test_reusing_prediction_id_with_changed_area_and_matching_costs_is_rejected(tmp_path):
    predictions, plans, costs = files(tmp_path)
    data = pd.read_csv(plans)
    data.loc[0, "area_m2"] = 2000
    data.to_csv(plans, index=False)
    costs["a"]["area_m2"] = 2000
    with pytest.raises(ValueError, match="plans hash"):
        connect_files(predictions, plans, costs, assume_one_cycle=True)


def test_modified_dsz_prediction_values_are_rejected(tmp_path):
    predictions, plans, costs = files(tmp_path)
    data = pd.read_csv(predictions)
    data.loc[0, "prediction"] = 5000
    data.to_csv(predictions, index=False)
    with pytest.raises(ValueError, match="prediction hash"):
        connect_files(predictions, plans, costs, assume_one_cycle=True)
