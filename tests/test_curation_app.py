"""Completed curation results must remain tied to their exact data and code."""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

import app as app_module


@pytest.fixture(params=[
    ("strawberry_curation", "reported_cycle_total_kg", "kg", "kg"),
    ("regional_curation", "revenue_krw_per_cycle", "krw", "원"),
])
def curation_result(tmp_path, monkeypatch, request):
    """Create synthetic local artifacts only; never alter actual model results."""
    prefix, target, metric, unit = request.param
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    data_path, code_path = tmp_path / "data.csv", tmp_path / "model.py"
    data_path.write_bytes(b"synthetic input\n")
    code_path.write_bytes(b"# synthetic model code\n")
    result = {
        "status": "completed", "target": target,
        "input_sha256": {data_path.name: hashlib.sha256(data_path.read_bytes()).hexdigest()},
        "limix": {"preprocessing_protocol": "train_only_regression_v2"},
        "stages": {name: {"status": "completed", "source_sha256": {
            code_path.name: hashlib.sha256(code_path.read_bytes()).hexdigest()}}
            for name in ["classical", "limix"]},
        "studies": {},
    }
    oof_paths = []
    for study in ["primary_recorded", "sensitivity_without_flagged_extreme"]:
        path = artifacts / f"{prefix}_{study}_oof.csv"
        path.write_bytes(b"source_id,prediction\nsynthetic,10\n")
        oof_paths.append(path)
        result["studies"][study] = {
            "oof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "models": {"limix_2_400m": {
                "n_scored": 1, f"mae_{metric}": 10, f"rmse_{metric}": 10}},
        }
    result_path = artifacts / f"{prefix}_metrics.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    ui = MagicMock()
    monkeypatch.setattr(app_module, "PROJECT", tmp_path)
    monkeypatch.setattr(app_module, "st", ui)
    return result, result_path, data_path, code_path, oof_paths, ui, unit


def test_completed_matching_results_show_both_studies_in_their_own_units(curation_result):
    *_, ui, unit = curation_result
    app_module.render_curation_validation()
    ui.subheader.assert_called_once()
    frame = ui.dataframe.call_args.args[0]
    assert len(frame) == 2
    assert set(frame["평가 범위"]) == {
        "주 결과 · 극단값 포함", "민감도 · 검토 대상 극단값 제외"}
    assert f"MAE ({unit}/작기)" in frame.columns
    assert ui.download_button.call_count == 2


@pytest.mark.parametrize("damage", [
    "running", "failed", "classical_incomplete", "limix_failed", "missing_study", "wrong_protocol",
])
def test_incomplete_or_incompatible_results_are_not_presented_as_completed(curation_result, damage):
    result, result_path, _, _, _, ui, _ = curation_result
    if damage in {"running", "failed"}:
        result["status"] = damage
    elif damage == "classical_incomplete":
        result["stages"]["classical"]["status"] = "running"
    elif damage == "limix_failed":
        result["stages"]["limix"]["status"] = "failed"
    elif damage == "missing_study":
        result["studies"].pop("primary_recorded")
    else:
        result["limix"]["preprocessing_protocol"] = "unverified"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    app_module.render_curation_validation()
    ui.subheader.assert_not_called()
    ui.dataframe.assert_not_called()
    ui.download_button.assert_not_called()


@pytest.mark.parametrize("changed_file", ["input", "code", "primary_oof", "sensitivity_oof"])
def test_changed_data_code_or_predictions_hide_stale_completed_results(curation_result, changed_file):
    _, _, data_path, code_path, oof_paths, ui, _ = curation_result
    paths = {"input": data_path, "code": code_path,
             "primary_oof": oof_paths[0], "sensitivity_oof": oof_paths[1]}
    paths[changed_file].write_bytes(b"different from the completed run\n")
    app_module.render_curation_validation()
    ui.subheader.assert_not_called()
    ui.dataframe.assert_not_called()
    ui.download_button.assert_not_called()
