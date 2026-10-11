"""Area-confirmed recorded-cycle models and explicit annual planning assumptions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import OneHotEncoder

from src.strawberry_curation_model import prepare_rows as strawberry_rows
from src.regional_curation_model import prepare_rows as regional_rows

CATEGORICAL = ["crop", "variety", "region", "district", "facility_type"]
NUMERIC = ["planting_year", "planting_month", "area_m2"]
FEATURES = CATEGORICAL + NUMERIC
METHODS = ["crop_area_median", "catboost_log_density", "xgboost_log_density"]
UNITS = {"shipment": "kg_per_recorded_cycle", "revenue": "krw_per_recorded_cycle"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_cohorts(project: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Verify source hashes; quarantine existing review flags without fixing values."""
    hashes = {}
    for name in ["strawberry", "regional"]:
        saved = json.loads((project / f"artifacts/{name}_curation_metrics.json").read_text(encoding="utf-8"))
        for relative, expected in saved["input_sha256"].items():
            path = project / relative
            if digest(path) != expected:
                raise ValueError(f"Source integrity differs: {relative}")
            hashes[relative.replace("\\", "/")] = expected
    manifest = json.loads((project / "data/processed/regional_curation_manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["api_metadata_sha256"].items():
        path = project / "data/processed" / name
        if digest(path) != expected:
            raise ValueError("Regional API metadata integrity differs")
    strawberry, _ = strawberry_rows(pd.read_csv(project / "data/processed/strawberry_curation_candidates.csv"))
    regional, _ = regional_rows(pd.read_csv(project / "data/processed/regional_curation_candidates.csv"))
    shipment = strawberry.loc[~strawberry.outlier_review].rename(columns={
        "region_sido": "region", "region_sigungu": "district", "farm_group": "group",
        "source_record_id": "record_id", "reported_cycle_total_kg": "target"}).copy()
    shipment["crop"] = "딸기"
    area = pd.to_numeric(regional.api_area_m2_verified_metadata, errors="coerce")
    eligible = np.isfinite(area) & area.gt(0) & ~regional.large_revenue_review_flag
    revenue = regional.loc[eligible].rename(columns={
        "cultivar": "variety", "province": "region", "district": "district",
        "facility_id": "group", "source_row_id": "record_id",
        "api_area_m2_verified_metadata": "area_m2", "revenue_krw_per_cycle": "target"}).copy()
    columns = FEATURES + ["target", "group", "record_id"]
    cohorts = {"shipment": shipment[columns].reset_index(drop=True),
               "revenue": revenue[columns].reset_index(drop=True)}
    audit = {"source_sha256": hashes,
             "policy": "API-confirmed m2 only; previously flagged scale records quarantined, never corrected. Primary original evaluations remain separate.",
             "target_period_confirmed": False,
             "shipment": {"primary_rows": len(strawberry), "eligible_rows": len(shipment),
                          "quarantined_ids": strawberry.loc[strawberry.outlier_review, "source_record_id"].tolist()},
             "revenue": {"primary_rows": len(regional), "eligible_rows": len(revenue),
                         "quarantined_ids": regional.loc[~eligible, "source_row_id"].tolist(),
                         "review_flag_count": int(regional.large_revenue_review_flag.sum()),
                         "unconfirmed_area_count": int((~np.isfinite(area) | area.le(0)).sum())}}
    return cohorts, audit


def _features(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows[FEATURES].copy()
    result[CATEGORICAL] = result[CATEGORICAL].fillna("__missing__").astype(str)
    for name in NUMERIC:
        result[name] = pd.to_numeric(result[name], errors="raise")
        if not np.isfinite(result[name]).all() or result[name].le(0).any():
            raise ValueError(f"Invalid positive planned feature: {name}")
    if not result.planting_month.between(1, 12).all() or (result.planting_month % 1 != 0).any():
        raise ValueError("Planting month must be a whole month from 1 to 12")
    if (result.planting_year % 1 != 0).any():
        raise ValueError("Planting year must be whole")
    return result


@dataclass
class PlanningModel:
    name: str
    medians: dict[str, float]
    encoder: Any = None
    estimator: Any = None

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        x = _features(rows)
        if not set(x.crop).issubset(self.medians):
            raise ValueError("Unsupported crop")
        if self.name == "crop_area_median":
            density = x.crop.map(self.medians).to_numpy(float)
        else:
            encoded = np.column_stack([self.encoder.transform(x[CATEGORICAL]), x[NUMERIC]])
            density = np.maximum(np.expm1(self.estimator.predict(encoded)), 0)
        return density * x.area_m2.to_numpy(float)


def fit_candidate(rows: pd.DataFrame, method: str) -> PlanningModel:
    """Fit only on training rows; density target prevents double area scaling."""
    x = _features(rows)
    density = rows.target.to_numpy(float) / x.area_m2.to_numpy(float)
    if not np.isfinite(density).all() or (density <= 0).any():
        raise ValueError("Expected positive finite target density")
    medians = pd.Series(density, index=rows.index).groupby(x.crop).median().to_dict()
    if method == "crop_area_median":
        return PlanningModel(method, medians)
    if method not in METHODS:
        raise ValueError("Unknown planning model")
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    encoded = np.column_stack([encoder.fit_transform(x[CATEGORICAL]), x[NUMERIC]])
    if method == "catboost_log_density":
        from catboost import CatBoostRegressor
        estimator = CatBoostRegressor(iterations=180, depth=3, learning_rate=.04,
                                      loss_function="MAE", l2_leaf_reg=5, random_seed=42,
                                      thread_count=2, verbose=False, allow_writing_files=False)
    else:
        from xgboost import XGBRegressor
        estimator = XGBRegressor(n_estimators=180, max_depth=3, learning_rate=.04,
                                 objective="reg:absoluteerror", reg_lambda=5,
                                 subsample=1, random_state=42, n_jobs=2)
    estimator.fit(encoded, np.log1p(density))
    return PlanningModel(method, medians, encoder, estimator)


def export_portable(model: PlanningModel) -> dict[str, Any]:
    """Export numeric tree equations only: no source records or farm identifiers."""
    output = {"model": model.name, "features": FEATURES, "medians": model.medians}
    if model.name == "crop_area_median":
        return output
    output["categories"] = [values.tolist() for values in model.encoder.categories_]
    if model.name == "catboost_log_density":
        # CatBoost's JSON writer requires a filename; this temporary file is local.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.estimator.save_model(str(path), format="json")
            native = json.loads(path.read_text(encoding="utf-8"))
        output["trees"] = [{"splits": [{"feature": split["float_feature_index"], "border": split["border"]}
                                       for split in tree.get("splits") or []],
                            "leaves": tree["leaf_values"]} for tree in native["oblivious_trees"]]
        output["scale"], bias = native["scale_and_bias"]
        output["bias"] = bias[0]
    else:
        native = json.loads(model.estimator.get_booster().save_raw(raw_format="json"))
        output["trees"] = [{key: tree[key] for key in ["left_children", "right_children", "split_indices", "split_conditions", "default_left"]}
                           for tree in native["learner"]["gradient_booster"]["model"]["trees"]]
        base = native["learner"]["learner_model_param"]["base_score"]
        output["bias"] = float(json.loads(base)[0] if base.startswith("[") else base)
    return output


def predict_portable(portable: dict[str, Any], rows: pd.DataFrame) -> np.ndarray:
    """Reference evaluator for the same portable equations executed in browsers."""
    x = _features(rows)
    if portable["model"] == "crop_area_median":
        density = x.crop.map(portable["medians"]).to_numpy(float)
    else:
        density = []
        for _, row in x.iterrows():
            encoded = [float(row[name] == value) for name, values in zip(CATEGORICAL, portable["categories"])
                       for value in values] + [float(np.float32(row[name])) for name in NUMERIC]
            total = 0.0
            for tree in portable["trees"]:
                if portable["model"] == "catboost_log_density":
                    index = sum((1 << depth) for depth, split in enumerate(tree["splits"])
                                if encoded[split["feature"]] > split["border"])
                    total += tree["leaves"][index]
                else:
                    index = 0
                    while tree["left_children"][index] != -1:
                        go_left = encoded[tree["split_indices"][index]] < tree["split_conditions"][index]
                        index = tree["left_children" if go_left else "right_children"][index]
                    total += tree["split_conditions"][index]
            log_density = total * portable.get("scale", 1) + portable["bias"]
            density.append(max(0, math.expm1(log_density)))
        density = np.array(density)
    result = density * x.area_m2.to_numpy(float)
    if not np.isfinite(result).all():
        raise ValueError("Unsupported or nonfinite portable prediction")
    return result


def _scores(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    error = predicted - actual
    return {"n": len(error), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean())),
            "median_absolute_error": float(np.median(np.abs(error)))}


def select_method(rows: pd.DataFrame) -> tuple[str, dict[str, float]]:
    """Inner facility-group validation; never receives the outer query targets."""
    scores = {name: [] for name in METHODS}
    splitter = GroupKFold(n_splits=min(3, rows.group.nunique()))
    for train, query in splitter.split(rows, groups=rows.group):
        observed = rows.iloc[query]
        for name in METHODS:
            model = fit_candidate(rows.iloc[train], name)
            supported = observed.crop.isin(model.medians)
            predictions = model.predict(observed.loc[supported])
            scores[name].extend(np.abs(predictions - observed.loc[supported, "target"]).tolist())
    means = {name: float(np.mean(errors)) for name, errors in scores.items()}
    return min(means, key=means.get), means


def validate_and_fit(rows: pd.DataFrame, target: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """Nested group CV, plus an earlier-years/unseen-facility temporal check."""
    rows = rows.reset_index(drop=True)
    output = rows[["record_id", "group", "crop", "target", "area_m2", "planting_year"]].copy()
    output["prediction"] = np.nan
    output["baseline"] = np.nan
    folds = []
    for number, (train, query) in enumerate(GroupKFold(n_splits=5).split(rows, groups=rows.group)):
        history, future = rows.iloc[train], rows.iloc[query]
        assert not set(history.group) & set(future.group)
        method, inner = select_method(history)
        model = fit_candidate(history, method)
        supported = future.crop.isin(model.medians)
        scored = future.loc[supported]
        output.loc[scored.index, "prediction"] = model.predict(scored)
        output.loc[scored.index, "baseline"] = fit_candidate(history, "crop_area_median").predict(scored)
        output.loc[future.index, "fold"] = number
        folds.append({"fold": number, "n_train": len(history), "n_query": len(future),
                      "selected": method, "inner_mae": inner, "unsupported_rows": int((~supported).sum()),
                      "group_overlap": 0})
    supported = output.prediction.notna()
    scored = output.loc[supported]
    metrics = {"nested_selection": _scores(scored.target.to_numpy(), scored.prediction.to_numpy()),
               "baseline": _scores(scored.target.to_numpy(), scored.baseline.to_numpy())}
    by_crop = {crop: {"selected": _scores(part.target.to_numpy(), part.prediction.to_numpy()),
                      "baseline": _scores(part.target.to_numpy(), part.baseline.to_numpy())}
               for crop, part in scored.groupby("crop")}
    cutoff = int(rows.planting_year.max())
    temporal_query = rows.loc[rows.planting_year.eq(cutoff)]
    history = rows.loc[rows.planting_year.lt(cutoff) & ~rows.group.isin(temporal_query.group)]
    temporal = {"query_year": cutoff, "n_train": len(history), "n_query": len(temporal_query), "group_overlap": 0}
    if history.group.nunique() >= 5 and len(history) >= 15:
        method, _ = select_method(history)
        model = fit_candidate(history, method)
        supported = temporal_query.crop.isin(model.medians)
        future = temporal_query.loc[supported]
        if len(future):
            temporal.update(status="evaluated", selected=method,
                            metrics=_scores(future.target.to_numpy(), model.predict(future)),
                            baseline=_scores(future.target.to_numpy(), fit_candidate(history, "crop_area_median").predict(future)),
                            unsupported_rows=int((~supported).sum()))
        else:
            temporal["status"] = "no_supported_crops"
    else:
        temporal["status"] = "insufficient_earlier_unseen_facility_history"
    selected, selection_scores = select_method(rows)
    model = fit_candidate(rows, selected)
    support = {"crops": sorted(rows.crop.unique().tolist()),
               "categories": {name: sorted(rows[name].fillna("__missing__").astype(str).unique().tolist()) for name in CATEGORICAL},
               "area_min_m2": float(rows.area_m2.min()), "area_max_m2": float(rows.area_m2.max()),
               "latest_planting_year": cutoff,
               "by_crop": {crop: {"n": len(part), "groups": int(part.group.nunique()),
                                  "area_min_m2": float(part.area_m2.min()), "area_max_m2": float(part.area_m2.max()),
                                  "locations": {region: sorted(region_rows.district.unique().tolist()) for region, region_rows in part.groupby("region")},
                                  "categories": {name: sorted(part[name].fillna("__missing__").astype(str).unique().tolist()) for name in CATEGORICAL}}
                           for crop, part in rows.groupby("crop")}}
    portable = export_portable(model)
    np.testing.assert_allclose(model.predict(rows), predict_portable(portable, rows), rtol=2e-6, atol=.1)
    bundle = {"target": target, "unit": UNITS[target], "portable": portable, "support": support,
              "validation": {"method": "nested_facility_group_cv_5_outer_3_inner", "folds": folds,
                             "metrics": metrics, "by_crop": by_crop, "temporal": temporal,
                             "unsupported_rows": int((~output.prediction.notna()).sum()),
                             "final_selection_mae": selection_scores},
              "target_period_confirmed": False,
              "limitations": ["Recorded-cycle totals, not certified complete annual performance.",
                              "Previously flagged scale records quarantined; primary raw-data evaluations retained separately.",
                              "API-confirmed area; raw regional source area is never converted.",
                              "Nested CV is an internal retrospective assessment, not a new external prospective trial.",
                              "Equipment productivity uplift and individual-farm investment effects are not learned."]}
    return bundle, output


def predict_plan(bundle: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    x = _features(pd.DataFrame([query]))
    crop = str(x.iloc[0].crop)
    if crop not in bundle["support"]["crops"]:
        return {"status": "unsupported_crop", "prediction": None, "target": bundle["target"]}
    support = bundle["support"].get("by_crop", {}).get(crop, bundle["support"])
    warnings = [f"unseen_{name}" for name in CATEGORICAL
                if str(x.iloc[0][name]) not in support["categories"][name]]
    if "locations" in support and query["district"] not in support["locations"].get(query["region"], []):
        warnings.append("unseen_region_district_combination")
    if not support["area_min_m2"] <= float(query["area_m2"]) <= support["area_max_m2"]:
        warnings.append("area_outside_training_range")
    if int(query["planting_year"]) > bundle["support"].get("latest_planting_year", 0):
        warnings.append("future_year_not_prospectively_validated")
    return {"status": "predicted", "target": bundle["target"], "unit": bundle["unit"],
            "prediction": float(predict_portable(bundle["portable"], x)[0]),
            "model": bundle["portable"]["model"], "query": x.iloc[0].to_dict(),
            "warnings": warnings, "target_period_confirmed": False}


def apply_prediction_to_plan(payload: dict[str, Any], prediction: dict[str, Any], *, acknowledge_period: bool) -> dict[str, Any]:
    """Bridge one reported cycle to one annual cycle only by explicit assumption."""
    if acknowledge_period is not True:
        raise ValueError("Recorded period must be explicitly assumed to represent one annual cycle")
    if payload["cycles_per_year"] != 1:
        raise ValueError("Existing annual costs require exactly one annual cycle")
    target = prediction.get("target")
    if prediction.get("status") != "predicted" or target not in UNITS or prediction.get("unit") != UNITS[target]:
        raise ValueError("Invalid prediction target, status or unit")
    value = prediction.get("prediction")
    if isinstance(value, bool) or value is None or not math.isfinite(float(value)) or value < 0:
        raise ValueError("Invalid prediction value")
    area = float(payload["area_m2"])
    if area <= 0 or not math.isfinite(area) or not math.isclose(area, float(prediction["query"]["area_m2"])):
        raise ValueError("Prediction query area differs from financial plan area")
    result = deepcopy(payload)
    if target == "shipment":
        result.pop("annual_revenue_override_krw", None)
        result["benchmark"]["yield_kg_per_1000m2"] = float(value) / area * 1000
    else:
        result["annual_revenue_override_krw"] = float(value)
    result["model_connection"] = {"prediction": prediction,
                                  "period_assumption": "one_recorded_cycle_per_year",
                                  "cost_basis": "unchanged annual per-1000m2 reference",
                                  "income_accuracy_validated": False}
    return result


def dsz_prediction_for_plan(row: dict[str, Any], planned_features: dict[str, Any]) -> dict[str, Any]:
    """Adapt the existing offline DSZ output without certifying its target period."""
    target = row.get("target")
    if target not in UNITS or row.get("unit") != {"shipment": "kg", "revenue": "KRW"}[target]:
        raise ValueError("DSZ target unit differs from its declared model contract")
    kind = row.get("data_kind")
    if kind not in {"synthetic_schema_fixture", "onsite_private_unverified"}:
        raise ValueError("DSZ source kind must remain explicit")
    area = float(planned_features["area_m2"])
    value = float(row["prediction"])
    if not math.isfinite(area) or area <= 0 or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid DSZ prediction or planned area")
    return {"status": "predicted", "target": target, "unit": UNITS[target], "prediction": value,
            "query": {"area_m2": area, "crop": planned_features["crop"]},
            "model": row["selected_cpu_model"], "data_kind": kind,
            "source_manifest_sha256": row["source_manifest_sha256"],
            "target_assumption": row["target_assumption"], "target_period_confirmed": False}


def load_planning_models(project: Path) -> dict[str, Any]:
    """Accept only models bound to the current verification report and code."""
    path = project / "reports/planning_models.json"
    summary = json.loads((project / "reports/planning_validation_summary.json").read_text(encoding="utf-8"))
    if digest(path) != summary["models_sha256"]:
        raise ValueError("Planning model hash differs from verification report")
    for relative, expected in summary["code_sha256"].items():
        if digest(project / relative) != expected:
            raise ValueError("Planning model code differs from verified implementation")
    return json.loads(path.read_text(encoding="utf-8"))["models"]
