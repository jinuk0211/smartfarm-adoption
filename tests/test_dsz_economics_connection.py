"""A matching plan ID must not bypass the exact original DSZ input provenance."""

import json

import pandas as pd
import pytest

from scripts.connect_dsz_economics import connect_files
from src.planning_models import digest
from src.dsz_period import evidence_digest


def files(tmp_path):
    plans = tmp_path / "plans.csv"
    predictions = tmp_path / "predictions.csv"
    declaration = {"schema_version": 1, "policy": "single_record_per_cycle", "data_kind": "synthetic_schema_fixture",
                   "target_columns": ["ALL_SHPMNT_KGUNT_QTY", "ALL_INCM_AMT"],
                   "source_files": [{"dataset": key, "file": key + ".csv", "sha256": "a" * 64} for key in ["DZ_002", "DZ_004"]],
                   "definition": {"path": "synthetic_test_only.txt", "sha256": "b" * 64, "locator": "fictional definition",
                                  "reviewed_by": "synthetic test", "reviewed_at": "2026-10-18",
                                  "aggregation_definition": "Fictional full cycle; no real farm observations."},
                   "cycles": [{"facility_id": "SYN_FARM_0", "cycle_id": "1", "start": "2021-01-01", "end": "2021-12-31",
                               "records": [{"source_row": 2, "start": "2021-01-01", "end": "2021-12-31"}]}]}
    proof = {key: value for key, value in declaration.items() if key != "cycles"}
    proof["cycle"] = declaration["cycles"][0]
    cohort = {"candidate_rows": 1, "used_rows": 1, "unconfirmed_excluded_rows": 0,
              "confirmed_ineligible_excluded_rows": 0, "source_all_periods_confirmed": True,
              "source_period_evidence_sha256": evidence_digest(declaration),
              "source_manifest_sha256": "fixture", "candidate_sha256": "c" * 64,
              "used_candidates": [{"row_id": "r0", "facility_id": "SYN_FARM_0", "cycle_id": "1",
                                   "target_period_evidence_sha256": evidence_digest(proof)}]}
    pd.DataFrame([{"plan_id": "a", "crop": "딸기", "area_m2": 1000}]).to_csv(plans, index=False)
    pd.DataFrame([{"plan_id": "a", "target": "shipment", "prediction": 4000, "unit": "kg",
                   "data_kind": "synthetic_schema_fixture", "selected_cpu_model": "xgboost",
                   "source_manifest_sha256": "fixture", "target_assumption": "single_record_per_cycle",
                   "target_period_confirmed": True, "target_period_evidence_sha256": evidence_digest(declaration),
                   "candidate_sha256": "c" * 64, "training_cohort_sha256": evidence_digest(cohort)}]).to_csv(predictions, index=False)
    predictions.with_suffix(".provenance.json").write_text(json.dumps({
        "prediction_sha256": digest(predictions), "plans_sha256": digest(plans), "rows": 1,
        "target_period_confirmation": declaration, "target_period_evidence_sha256": evidence_digest(declaration),
        "training_cohort": cohort, "training_cohort_sha256": evidence_digest(cohort)}), encoding="utf-8")
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
    assert results[0]["inputs"]["model_connection"]["prediction"]["target_period_confirmed"] is True


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


@pytest.mark.parametrize("damage", ["unconfirmed", "missing_definition"])
def test_annual_assumption_cannot_bypass_missing_period_evidence(tmp_path, damage):
    predictions, plans, costs = files(tmp_path)
    sidecar = predictions.with_suffix(".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    if damage == "unconfirmed":
        data = pd.read_csv(predictions)
        data["target_period_confirmed"] = False
        data.to_csv(predictions, index=False)
        provenance["prediction_sha256"] = digest(predictions)
    else:
        provenance.pop("target_period_confirmation")
    sidecar.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError, match="period"):
        connect_files(predictions, plans, costs, assume_one_cycle=True)


@pytest.mark.parametrize("plan_id", ["NA", "NULL", "00001"])
def test_literal_plan_identifiers_survive_financial_bridge(tmp_path, plan_id):
    predictions, plans, costs = files(tmp_path)
    for path in [predictions, plans]:
        data = pd.read_csv(path, keep_default_na=False)
        data["plan_id"] = plan_id
        data.to_csv(path, index=False)
    sidecar = predictions.with_suffix(".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    provenance.update(prediction_sha256=digest(predictions), plans_sha256=digest(plans))
    sidecar.write_text(json.dumps(provenance), encoding="utf-8")
    costs[plan_id] = costs.pop("a")
    assert connect_files(predictions, plans, costs, assume_one_cycle=True)[0]["plan_id"] == plan_id
