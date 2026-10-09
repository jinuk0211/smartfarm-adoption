"""DSZ offline contract behavior; fixtures are not real farm observations."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from scripts.predict_dsz import predict_from_artifacts
from scripts.train_dsz import read_data, train
from src.dsz_model import (FEATURES, CropMedian, features, fit_target, grouped_folds, predict_plans,
                           prepare_target, sha256)


def candidates():
    return pd.DataFrame([{
        "row_id": f"r{i}", "facility_id": f"SYN_FARM_{i // 2}", "cycle_id": f"c{i}",
        "crop": "딸기", "region": "테스트지역", "greenhouse_type": "단동", "greenhouse_size": "소형",
        "area_m2": 1000 + i * 10, "planned_start_year": 2024, "planned_start_month": 9,
        "reported_shipment_kg": i * 100., "reported_revenue_krw": i * 1000.,
        "shipment_eligible": True, "revenue_eligible": True,
        "data_kind": "synthetic_schema_fixture", "target_assumption": "single_record_per_cycle",
    } for i in range(8)])


def bundle(rows):
    return {"features": FEATURES, "model": CropMedian().fit(features(rows), rows["reported_shipment_kg"]),
            "training_crops": ["딸기"], "target": "shipment", "unit": "kg",
            "data_kind": "synthetic_schema_fixture", "target_assumption": "single_record_per_cycle",
            "target_period_confirmed": False,
            "source_manifest_sha256": "test-only-source", "selected_cpu_model": "crop_median"}


def test_future_and_target_columns_cannot_enter_features():
    rows = candidates()
    before = features(rows)
    for name in ["reported_shipment_kg", "reported_revenue_krw", "actual_end_date", "actual_temperature",
                 "facility_id", "cycle_id", "target_assumption", "shipment_eligible"]:
        rows[name] = "changed_outcome"
    pd.testing.assert_frame_equal(features(rows), before)


def test_targets_keep_observed_zero_and_handle_missing_independently():
    rows = candidates()
    rows.loc[1, "reported_shipment_kg"] = np.nan
    rows.loc[1, "shipment_eligible"] = False
    shipment = prepare_target(rows, "shipment")
    revenue = prepare_target(rows, "revenue")
    assert len(shipment) == 7 and len(revenue) == 8
    assert shipment.loc[shipment["row_id"].eq("r0"), "reported_shipment_kg"].item() == 0
    rows.loc[1, "shipment_eligible"] = True
    with pytest.raises(ValueError, match="nonnegative"):
        prepare_target(rows, "shipment")


def test_adaptive_folds_keep_all_facility_cycles_together():
    rows = candidates()
    folds = grouped_folds(rows)
    assert len(folds) == 4
    assert sorted(np.concatenate([query for _, query in folds])) == list(range(8))
    for training, query in folds:
        assert set(rows.iloc[training].facility_id).isdisjoint(rows.iloc[query].facility_id)
    with pytest.raises(ValueError, match="two independent"):
        grouped_folds(rows.iloc[:2])


def test_training_only_area_baseline_ignores_heldout_labels():
    training, query = candidates().iloc[:4], candidates().iloc[4:].copy()
    model = CropMedian(area_scaled=True).fit(features(training), training.reported_shipment_kg)
    before = model.predict(features(query))
    query["reported_shipment_kg"] = 1e20
    np.testing.assert_array_equal(model.predict(features(query)), before)
    np.testing.assert_allclose(before, query.area_m2 * np.median(training.reported_shipment_kg / training.area_m2))


def test_plan_prediction_propagates_synthetic_origin_and_exact_schema():
    rows = candidates()
    plan = rows[FEATURES].iloc[:2].copy()
    result = predict_plans(bundle(rows), plan)
    assert result.data_kind.eq("synthetic_schema_fixture").all()
    assert result.interpretation.str.startswith("SYNTHETIC RUNTIME DEMO").all()
    assert result.target_assumption.eq("single_record_per_cycle").all()
    plan["reported_shipment_kg"] = 100
    with pytest.raises(ValueError, match="seven planned"):
        predict_plans(bundle(rows), plan)


@pytest.mark.parametrize("column,value", [("area_m2", 0), ("planned_start_month", 13),
                                         ("planned_start_year", 2026.5), ("crop", "오이")])
def test_invalid_or_unsupported_plan_is_rejected(column, value):
    rows = candidates()
    plan = rows[FEATURES].iloc[:1].copy().astype({"planned_start_year": float})
    plan[column] = value
    with pytest.raises(ValueError):
        predict_plans(bundle(rows), plan)


def test_artifact_hash_checked_before_loading_and_tag_survives(tmp_path, monkeypatch):
    rows = candidates()
    path = tmp_path / "dsz_shipment.joblib"
    saved = bundle(rows)
    joblib.dump(saved, path)
    manifest = {"status": "completed", **{key: saved[key] for key in
                ["data_kind", "target_assumption", "target_period_confirmed", "source_manifest_sha256"]},
                "source_sha256": {name: sha256(Path(__file__).resolve().parents[1] / name) for name in
                                  ["src/dsz_model.py", "scripts/predict_dsz.py"]},
                "targets": {"shipment": {"status": "completed", "artifact_file": path.name, "artifact_sha256": sha256(path)}}}
    (tmp_path / "dsz_model_metrics.json").write_text(json.dumps(manifest), encoding="utf-8")
    predicted = predict_from_artifacts(tmp_path, rows[FEATURES].iloc[:1])
    assert predicted.data_kind.item() == "synthetic_schema_fixture"
    assert not predicted.target_period_confirmed.item()
    manifest["source_sha256"]["src/dsz_model.py"] = "modified-code"
    (tmp_path / "dsz_model_metrics.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Current prediction source"):
        predict_from_artifacts(tmp_path, rows[FEATURES].iloc[:1])
    manifest["source_sha256"]["src/dsz_model.py"] = sha256(Path(__file__).resolve().parents[1] / "src/dsz_model.py")
    (tmp_path / "dsz_model_metrics.json").write_text(json.dumps(manifest), encoding="utf-8")
    path.write_bytes(b"not the declared local artifact")
    monkeypatch.setattr(joblib, "load", lambda _: pytest.fail("Changed artifact must not be unpickled"))
    with pytest.raises(ValueError, match="SHA"):
        predict_from_artifacts(tmp_path, rows[FEATURES].iloc[:1])


def test_manifest_provenance_mismatch_and_early_failure_invalidate_old_success(tmp_path):
    rows = candidates()
    path = tmp_path / "dsz_model_candidates.csv"
    rows.to_csv(path, index=False)
    manifest = {"features": FEATURES, "data_kind": "onsite_private_unverified",
                "target_assumption": "single_record_per_cycle", "target_period_confirmed": False,
                "schema_sha256": "test-only-schema", "artifacts": {"candidates": {"file": path.name, "sha256": sha256(path)}}}
    (tmp_path / "dsz_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance mismatch"):
        read_data(tmp_path)
    output = tmp_path / "models"
    output.mkdir()
    metrics = output / "dsz_model_metrics.json"
    metrics.write_text('{"status":"completed"}', encoding="utf-8")
    with pytest.raises(ValueError):
        train(tmp_path, output)
    assert json.loads(metrics.read_text(encoding="utf-8"))["status"] == "failed"


def write_inputs(directory, rows):
    path = directory / "dsz_model_candidates.csv"
    rows.to_csv(path, index=False)
    manifest = {"features": FEATURES, "data_kind": rows.data_kind.iloc[0],
                "target_assumption": "single_record_per_cycle", "target_period_confirmed": False,
                "schema_sha256": "test-only-schema", "target_units": {"reported_shipment_kg": "kg", "reported_revenue_krw": "KRW"},
                "artifacts": {"candidates": {"file": path.name, "sha256": sha256(path)}}}
    (directory / "dsz_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_numeric_looking_ids_keep_leading_zeros_long_precision_and_literal_na(tmp_path):
    rows = candidates()
    rows["data_kind"] = "onsite_private_unverified"
    ids = ["00001", "1", "123456789012345678901234567890", "NA"]
    rows["facility_id"] = np.repeat(ids, 2)
    rows["row_id"] = [f"{i:025d}" for i in range(8)]
    rows["cycle_id"] = [f"{i:06d}" for i in range(8)]
    rows.loc[1, "reported_revenue_krw"] = np.nan
    rows.loc[1, "revenue_eligible"] = False
    write_inputs(tmp_path, rows)
    loaded, _, _ = read_data(tmp_path)
    for name in ["facility_id", "row_id", "cycle_id"]:
        assert loaded[name].tolist() == rows[name].tolist()
    assert pd.isna(loaded.loc[1, "reported_revenue_krw"])
    assert len(grouped_folds(loaded)) == 4


@pytest.mark.parametrize("remaining_revenue_rows", [0, 2])
def test_one_target_insufficient_does_not_prevent_other_training_or_prediction(tmp_path, monkeypatch, remaining_revenue_rows):
    rows = candidates()
    rows["revenue_eligible"] = False
    if remaining_revenue_rows:
        rows.loc[:remaining_revenue_rows - 1, "revenue_eligible"] = True
    write_inputs(tmp_path, rows)
    monkeypatch.setattr("src.dsz_model.make_model", lambda _: CropMedian())
    output = tmp_path / "models"
    summary = train(tmp_path, output)
    assert summary["status"] == "completed"
    assert summary["targets"]["revenue"]["status"] == "skipped_insufficient_data"
    assert summary["targets"]["shipment"]["status"] == "completed"
    predicted = predict_from_artifacts(output, rows[FEATURES].iloc[:1])
    assert predicted.target.tolist() == ["shipment"]


def test_both_targets_insufficient_fail_without_success_artifact(tmp_path):
    rows = candidates()
    rows[["shipment_eligible", "revenue_eligible"]] = False
    write_inputs(tmp_path, rows)
    output = tmp_path / "models"
    with pytest.raises(ValueError, match="Neither target"):
        train(tmp_path, output)
    result = json.loads((output / "dsz_model_metrics.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert all(item["status"] == "skipped_insufficient_data" for item in result["targets"].values())


@pytest.mark.parametrize("case", ["all_zero", "constant_each_facility", "constant_features"])
def test_valid_degenerate_training_folds_produce_audited_predictions(case):
    rows = candidates()
    if case == "all_zero":
        rows["reported_shipment_kg"] = 0.0
    elif case == "constant_each_facility":
        rows = rows.iloc[:4].copy()
        rows["reported_shipment_kg"] = [0., 0., 500., 500.]
    else:
        rows[FEATURES] = rows[FEATURES].iloc[0].to_numpy()
    provenance = {"data_kind": "synthetic_schema_fixture", "target_assumption": "single_record_per_cycle",
                  "target_period_confirmed": False, "source_manifest_sha256": "test-only-source"}
    saved, oof, summary = fit_target(prepare_target(rows, "shipment"), "shipment", provenance)
    assert summary["constant_training_fallbacks"]
    assert set(item["method"] for item in summary["constant_training_fallbacks"]) == {"catboost", "xgboost"}
    assert np.isfinite(oof[["crop_median", "area_scaled_crop_median", "catboost", "xgboost"]]).all().all()
    if case == "all_zero":
        assert oof[["crop_median", "area_scaled_crop_median", "catboost", "xgboost"]].eq(0).all().all()
        assert predict_plans(saved, rows[FEATURES].iloc[:1]).prediction.item() == 0
