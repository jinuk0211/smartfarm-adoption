"""Behavioral tests for the offline, fixed-cutoff shipment workflow."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import joblib
import numpy as np
import pandas as pd
import pytest

from src.dsz_data import prepare
from src.dsz_inseason import (IDENTITY, LABEL, TrainFoldModel, join_training_rows, latest_year_check,
                              load_local_bundle, model_features, predict_inseason, train_inseason)
from src.dsz_model import FEATURES, CropMedian
from src.dsz_observations import OBSERVATION_NUMERIC, build_observation_features, load_observation_tables

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs(tmp_path):
    raw = tmp_path / "raw"
    query = tmp_path / "query"
    shutil.copytree(ROOT / "data/examples/dsz_inseason/input", raw)
    shutil.copytree(ROOT / "data/examples/dsz_inseason/query", query)
    prepared = tmp_path / "prepared"
    prepare(raw, prepared, period_confirmation=raw / "period_confirmation.json")
    return raw, prepared, query


@pytest.fixture
def fast_models(monkeypatch):
    def fit(method, x, y, **kwargs):
        return CropMedian(area_scaled=method == "area_scaled_crop_median").fit(x, y), None
    monkeypatch.setattr("src.dsz_inseason.fit_cpu", fit)


def requests():
    return pd.read_csv(ROOT / "data/examples/dsz_inseason/requests.csv", dtype=str, keep_default_na=False)


def test_confirmed_target_gate_cannot_be_bypassed(inputs, tmp_path, fast_models):
    raw, _, _ = inputs
    unconfirmed = tmp_path / "unconfirmed"
    prepare(raw, unconfirmed)
    with pytest.raises(ValueError, match="confirmed eligible"):
        train_inseason(unconfirmed, raw, tmp_path / "blocked")
    assert json.loads((tmp_path / "blocked/dsz_inseason_metrics.json").read_text())["status"] == "failed"
    assert not (tmp_path / "blocked/dsz_inseason_shipment.joblib").exists()


def test_raw_source_mutation_requires_repreparation(inputs, tmp_path, fast_models):
    raw, prepared, _ = inputs
    path = raw / "DZ_001.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Raw source files/SHA"):
        train_inseason(prepared, raw, tmp_path / "changed")


def test_shared_cohort_whitelist_and_same_prediction_feature_builder(inputs, tmp_path, fast_models):
    raw, prepared, query = inputs
    output = tmp_path / "models"
    summary = train_inseason(prepared, raw, output)
    assert summary["same_rows_and_folds_for_all_candidates"] is True
    assert summary["data_kind"] == "synthetic_schema_fixture"
    assert summary["prediction_scope"] == "inseason_cycle_total"
    rows = pd.read_csv(output / "dsz_inseason_training_rows.csv", dtype={name: str for name in IDENTITY})
    before = model_features(rows, True)
    altered = rows.copy()
    for column in [LABEL, "reported_revenue_krw", "facility_id", "cycle_id", "row_id", "as_of", "raw_json"]:
        altered[column] = "injected"
    pd.testing.assert_frame_equal(before, model_features(altered, True))
    assert list(before.columns) == FEATURES + OBSERVATION_NUMERIC
    for fold in summary["folds"]:
        train = rows.loc[rows.row_id.isin(fold["train_row_ids"])]
        test = rows.loc[rows.row_id.isin(fold["test_row_ids"])]
        assert set(train.facility_id).isdisjoint(test.facility_id)
    oof = pd.read_csv(output / "dsz_inseason_oof.csv")
    assert len(oof) == len(rows) == summary["rows"]
    np.testing.assert_array_equal(oof.baseline__crop_median, oof.extended__crop_median)
    np.testing.assert_array_equal(oof.baseline__area_scaled_crop_median, oof.extended__area_scaled_crop_median)
    prediction, meta = predict_inseason(output, query, requests())
    bundle, _ = load_local_bundle(output)
    tables, _, _ = load_observation_tables(query)
    x, _ = build_observation_features(tables, requests().rename(columns={"plan_id": "row_id"}), 30, 28)
    np.testing.assert_array_equal(prediction.prediction, bundle["model"].predict(x))
    assert prediction.unit.eq("kg").all()
    assert prediction.prediction_scope.eq("inseason_cycle_total").all()
    assert prediction.interpretation.eq("SYNTHETIC RUNTIME DEMO ONLY").all()
    assert meta["raw_sources"]
    with pytest.raises(FileExistsError):
        train_inseason(prepared, raw, output)


def test_imputation_is_fit_only_on_training_and_medians_ignore_observations(monkeypatch):
    x = pd.DataFrame({"crop": ["딸기"] * 3, "region": ["a"] * 3, "greenhouse_type": ["단동"] * 3,
                      "greenhouse_size": ["1동"] * 3, "area_m2": [1000.] * 3,
                      "planned_start_year": [2024] * 3, "planned_start_month": [9] * 3})
    for name in OBSERVATION_NUMERIC:
        x[name] = np.nan
    selected = OBSERVATION_NUMERIC[0]
    x[selected] = [10., 30., np.nan]
    captured = []
    def fit(method, values, y, **kwargs):
        captured.append((values.copy(), kwargs))
        return CropMedian().fit(values, y), None
    monkeypatch.setattr("src.dsz_inseason.fit_cpu", fit)
    model = TrainFoldModel("xgboost", True).fit(x, [1., 2., 3.])
    assert captured[0][0][selected].tolist() == [10., 30., 20.]
    assert f"missingindicator_{selected}" in captured[0][0]
    assert set(captured[0][1]["numeric_features"]).isdisjoint(IDENTITY + [LABEL])
    statistics = model.imputer.statistics_.copy()
    query = x.iloc[:1].copy()
    query[selected] = 1e9
    model.predict(query)
    np.testing.assert_array_equal(statistics, model.imputer.statistics_)
    TrainFoldModel("crop_median", True).fit(x, [1., 2., 3.])
    assert list(captured[-1][0].columns) == FEATURES


def test_no_observation_or_wrong_identity_query_fails_without_fallback(inputs, tmp_path, fast_models):
    raw, prepared, query = inputs
    output = tmp_path / "models"
    train_inseason(prepared, raw, output)
    wrong = requests()
    wrong["facility_id"] = "SYN_FARM_UNKNOWN"
    with pytest.raises(ValueError, match="no silent baseline fallback"):
        predict_inseason(output, query, wrong)
    for path in query.glob("*.csv"):
        if path.name != "DZ_002.csv":
            table = pd.read_csv(path)
            table.iloc[:0].to_csv(path, index=False)
    with pytest.raises(ValueError, match="no silent baseline fallback"):
        predict_inseason(output, query, requests())


def test_artifact_and_source_hashes_are_checked_before_unpickling(inputs, tmp_path, fast_models, monkeypatch):
    raw, prepared, _ = inputs
    output = tmp_path / "models"
    train_inseason(prepared, raw, output)
    path = output / "dsz_inseason_metrics.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    original = manifest["source_sha256"]["src/dsz_observations.py"]
    manifest["source_sha256"]["src/dsz_observations.py"] = "changed"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(joblib, "load", lambda _: pytest.fail("Changed files must not be unpickled"))
    with pytest.raises(ValueError, match="source hashes"):
        load_local_bundle(output)
    manifest["source_sha256"]["src/dsz_observations.py"] = original
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (output / manifest["artifact_file"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact path/SHA"):
        load_local_bundle(output)


def test_query_scope_future_cutoff_and_extra_fields_are_rejected(inputs, tmp_path, fast_models, monkeypatch):
    raw, prepared, query = inputs
    output = tmp_path / "models"
    train_inseason(prepared, raw, output)
    extra = requests().assign(reported_shipment_kg=999.)
    with pytest.raises(ValueError, match="only plan_id"):
        predict_inseason(output, query, extra)
    original = build_observation_features
    def altered(tables, request_rows, cutoff_days, window_days):
        rows, audit = original(tables, request_rows, cutoff_days, window_days)
        rows["as_of"] = "2099-01-31T00:00:00"
        return rows, audit
    monkeypatch.setattr("src.dsz_inseason.build_observation_features", altered)
    with pytest.raises(ValueError, match="cutoff is in the future"):
        predict_inseason(output, query, requests())
    monkeypatch.setattr("src.dsz_inseason.build_observation_features", original)
    path = query / "DZ_002.csv"
    facility = pd.read_csv(path, dtype=str, keep_default_na=False)
    facility["ITEM_NM"] = "오이"
    facility.to_csv(path, index=False)
    with pytest.raises(ValueError, match="crop is outside"):
        predict_inseason(output, query, requests())


def test_join_rejects_different_facility_metadata():
    rows = pd.DataFrame([{**dict.fromkeys(IDENTITY, "id"), "crop": "딸기", "region": "region",
                          "greenhouse_type": "단동", "greenhouse_size": "1동", "area_m2": 1000.,
                          "planned_start_year": 2024, "planned_start_month": 9}])
    observations = rows.copy()
    observations["area_m2"] = 2000.
    observations["has_observations"] = True
    with pytest.raises(ValueError, match="feature mismatch: area_m2"):
        join_training_rows(rows, observations)


def test_latest_year_check_excludes_test_facilities_and_unfinished_labels(fast_models):
    rows = pd.DataFrame({"row_id": ["a", "b", "c", "d", "e"], "facility_id": ["A", "B", "C", "A", "D"],
                         "planned_start_year": [2022, 2022, 2022, 2023, 2023],
                         "as_of": ["2022-02-01"] * 3 + ["2023-02-01"] * 2,
                         "target_period_evidence_json": [json.dumps({"cycle": {"end": value}}) for value in
                             ["2022-06-01", "2023-03-01", "2022-06-01", "2023-06-01", "2023-06-01"]]})
    rows["management_raw_json"] = json.dumps([{"EXMN_YMD": "20220601"}])
    result = latest_year_check(rows)
    # A is excluded by facility overlap, B by future label completion, leaving only C.
    assert result["status"] == "skipped"
    assert result["train_rows"] == 1


def test_temporal_training_rejects_late_missing_and_malformed_survey_dates(fast_models):
    rows = pd.DataFrame([{
        "row_id": f"r{i}", "facility_id": f"F{i}", "cycle_id": f"C{i}",
        "crop": "딸기", "region": "test", "greenhouse_type": "단동", "greenhouse_size": "1동",
        "area_m2": 1000., "planned_start_year": 2023 if i == 5 else 2022, "planned_start_month": 1,
        "as_of": "2023-02-01" if i == 5 else "2022-02-01", LABEL: float(i * 100),
        "target_period_evidence_json": json.dumps({"cycle": {"end": "2022-06-30"}}),
        "management_raw_json": json.dumps([{"EXMN_YMD": "20220630"}]),
        **dict.fromkeys(OBSERVATION_NUMERIC, 1.),
    } for i in range(6)])
    # The survey day immediately before the cutoff is complete and may be used.
    rows.loc[1, "management_raw_json"] = json.dumps([{"EXMN_YMD": "20230131"}])
    # An early cycle end cannot make a later survey label available in the past.
    rows.loc[2, "management_raw_json"] = json.dumps([{"EXMN_YMD": "20220630"}, {"EXMN_YMD": "20230201"}])
    rows.loc[3, "management_raw_json"] = json.dumps([{}])
    rows.loc[4, "management_raw_json"] = json.dumps([{"EXMN_YMD": "not-a-date"}])
    result = latest_year_check(rows)
    assert result["status"] == "completed"
    assert result["train_row_ids"] == ["r0", "r1"]
    assert result["test_row_ids"] == ["r5"]
    assert result["exclusion_counts"] == {
        "missing_or_invalid_label_availability_date": 2, "label_not_available_by_test_cutoff": 1}
    late = next(item for item in result["training_exclusions"] if item["row_id"] == "r2")
    assert late["label_available_after"] == "2023-02-02T00:00:00"
