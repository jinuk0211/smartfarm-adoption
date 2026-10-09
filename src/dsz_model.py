"""Offline recorded-cycle candidate models; synthetic results are runtime tests only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

NUMERIC = ["area_m2", "planned_start_year", "planned_start_month"]
CATEGORICAL = ["crop", "region", "greenhouse_type", "greenhouse_size"]
FEATURES = CATEGORICAL + NUMERIC
TARGETS = {"shipment": ("reported_shipment_kg", "shipment_eligible", "kg"),
           "revenue": ("reported_revenue_krw", "revenue_eligible", "KRW")}
METHODS = ["crop_median", "area_scaled_crop_median", "catboost", "xgboost"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def features(rows: pd.DataFrame) -> pd.DataFrame:
    missing = set(FEATURES) - set(rows.columns)
    if missing:
        raise ValueError(f"Missing planned feature columns: {sorted(missing)}")
    result = rows[FEATURES].copy()
    for name in CATEGORICAL:
        result[name] = result[name].fillna("__missing__").astype(str).replace("", "__missing__")
    if result["crop"].isin(["", "__missing__"]).any():
        raise ValueError("crop must be specified")
    for name in NUMERIC:
        result[name] = pd.to_numeric(result[name], errors="raise")
        if not np.isfinite(result[name]).all():
            raise ValueError(f"Feature must be finite: {name}")
    if result["area_m2"].le(0).any():
        raise ValueError("area_m2 must be positive, in square metres")
    for name in ["planned_start_year", "planned_start_month"]:
        if result[name].mod(1).ne(0).any():
            raise ValueError(f"Feature must be an integer: {name}")
    if not result["planned_start_month"].between(1, 12).all():
        raise ValueError("planned_start_month must be 1..12")
    return result


def prepare_target(candidates: pd.DataFrame, target: str) -> pd.DataFrame:
    label, eligible, _ = TARGETS[target]
    required = FEATURES + [label, eligible, "row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]
    if missing := set(required) - set(candidates.columns):
        raise ValueError(f"Missing candidate columns: {sorted(missing)}")
    if not candidates[eligible].isin([True, False]).all():
        raise ValueError(f"Expected explicit boolean eligibility: {eligible}")
    rows = candidates.loc[candidates[eligible].eq(True)].copy()
    if rows["row_id"].duplicated().any() or rows.duplicated(["facility_id", "cycle_id"]).any():
        raise ValueError("Duplicate candidate identity")
    identity = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]]
    if identity.isna().any().any() or identity.eq("").any().any():
        raise ValueError("Missing identity or data provenance")
    rows[label] = pd.to_numeric(rows[label], errors="raise")
    if not np.isfinite(rows[label]).all() or rows[label].lt(0).any():
        raise ValueError("Eligible target must be finite and nonnegative; missing is not zero")
    features(rows)
    return rows.sort_values("row_id").reset_index(drop=True)


def grouped_folds(rows: pd.DataFrame):
    count = int(rows["facility_id"].nunique())
    if count < 2:
        raise ValueError("At least two independent facility IDs are required")
    folds = list(GroupKFold(n_splits=min(5, count)).split(rows, groups=rows["facility_id"]))
    seen = np.zeros(len(rows), dtype=int)
    for train, query in folds:
        if set(rows.iloc[train]["facility_id"]) & set(rows.iloc[query]["facility_id"]):
            raise ValueError("Facility overlap")
        seen[query] += 1
    if not np.all(seen == 1):
        raise ValueError("Every row needs exactly one held-out prediction")
    return folds


class CropMedian:
    """Training-only crop medians, optionally per square metre."""

    def __init__(self, area_scaled: bool = False):
        self.area_scaled = area_scaled

    def fit(self, x: pd.DataFrame, y):
        values = np.asarray(y, dtype=float)
        if self.area_scaled:
            values = values / x["area_m2"].to_numpy(float)
        rows = pd.DataFrame({"crop": x["crop"].to_numpy(), "value": values})
        self.medians = rows.groupby("crop")["value"].median().to_dict()
        self.global_median = float(np.median(values))
        return self

    def predict(self, x: pd.DataFrame):
        values = x["crop"].map(self.medians).fillna(self.global_median).to_numpy(float)
        return values * x["area_m2"].to_numpy(float) if self.area_scaled else values


def make_model(name: str):
    if name in METHODS[:2]:
        return CropMedian(area_scaled=name == "area_scaled_crop_median")
    if name == "catboost":
        from catboost import CatBoostRegressor
        return CatBoostRegressor(iterations=180, depth=4, learning_rate=0.05, loss_function="MAE",
                                 l2_leaf_reg=5, random_seed=42, thread_count=2,
                                 cat_features=CATEGORICAL, allow_writing_files=False, verbose=False)
    if name == "xgboost":
        from sklearn.compose import ColumnTransformer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        from xgboost import XGBRegressor
        return Pipeline([
            ("encode", ColumnTransformer([
                ("category", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
                ("numeric", "passthrough", NUMERIC)])),
            ("model", XGBRegressor(n_estimators=180, max_depth=3, learning_rate=0.05,
                                   objective="reg:absoluteerror", reg_lambda=5,
                                   subsample=0.9, random_state=42, n_jobs=2))])
    raise ValueError(f"Unknown CPU method: {name}")


def scores(actual, predicted) -> dict:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if not len(actual) or len(actual) != len(predicted) or not np.isfinite(predicted).all():
        raise ValueError("Missing/nonfinite predictions")
    error = predicted - actual
    return {"n_scored": len(actual), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean()))}


def fit_cpu(name, x, y):
    """Audit degenerate ML folds instead of failing on valid zero/constant labels."""
    reason = None
    if name in {"catboost", "xgboost"}:
        if pd.Series(np.asarray(y)).nunique() == 1:
            reason = "constant_training_target"
        elif x.nunique(dropna=False).le(1).all():
            reason = "constant_training_features"
    model = CropMedian() if reason else make_model(name)
    return model.fit(x, y), reason


def fit_target(rows: pd.DataFrame, target: str, provenance: dict):
    label, _, unit = TARGETS[target]
    folds = grouped_folds(rows)
    x = features(rows)
    oof = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption", label]].copy()
    oof["fold"] = -1
    oof["crop_seen_in_training"] = False
    oof["source_manifest_sha256"] = provenance["source_manifest_sha256"]
    for name in METHODS:
        oof[name] = np.nan
    records, fallbacks = [], []
    for number, (train, query) in enumerate(folds):
        for name in METHODS:
            model, reason = fit_cpu(name, x.iloc[train], rows.iloc[train][label])
            if reason:
                fallbacks.append({"fold": number, "method": name, "reason": reason,
                                  "replacement": "training-only median"})
            oof.loc[query, name] = np.maximum(model.predict(x.iloc[query]), 0)
        oof.loc[query, "fold"] = number
        oof.loc[query, "crop_seen_in_training"] = rows.iloc[query]["crop"].isin(rows.iloc[train]["crop"]).to_numpy()
        records.append({"fold": number, "train_row_ids": rows.iloc[train]["row_id"].tolist(),
                        "test_row_ids": rows.iloc[query]["row_id"].tolist(),
                        "train_facilities": int(rows.iloc[train]["facility_id"].nunique()),
                        "test_facilities": int(rows.iloc[query]["facility_id"].nunique()), "facility_overlap": False})
    metrics = {name: {**scores(rows[label], oof[name]),
                     "by_fold": {str(fold): scores(group[label], group[name]) for fold, group in oof.groupby("fold")},
                     "by_crop": {str(crop): scores(rows.loc[group.index, label], group[name])
                                 for crop, group in oof.groupby(rows["crop"])}}
               for name in METHODS}
    selected = min(METHODS, key=lambda name: metrics[name]["mae"])
    model, final_fallback = fit_cpu(selected, x, rows[label])
    bundle = {**provenance, "target": target, "target_column": label, "unit": unit,
              "features": FEATURES, "selected_cpu_model": selected, "model": model,
              "selected_model_fallback": final_fallback,
              "training_crops": sorted(rows["crop"].unique().tolist()), "training_rows": len(rows),
              "selection": "lowest same-row facility-group OOF MAE; no untouched final test"}
    summary = {"status": "completed", "target_column": label, "unit": unit, "rows": len(rows),
               "facilities": int(rows["facility_id"].nunique()), "zero_target_rows": int(rows[label].eq(0).sum()),
               "unseen_crop_oof_rows": int((~oof["crop_seen_in_training"]).sum()),
               "folds": records, "models": metrics, "selected_cpu_model": selected,
               "constant_training_fallbacks": fallbacks, "selected_model_fallback": final_fallback}
    return bundle, oof, summary


def predict_plans(bundle: dict, plans: pd.DataFrame) -> pd.DataFrame:
    """Use only a locally generated, trusted bundle; preserve training-data kind."""
    if set(plans.columns) - set(FEATURES + ["plan_id"]):
        raise ValueError("Plans may contain only the seven planned features and optional plan_id")
    if bundle["features"] != FEATURES:
        raise ValueError("Artifact feature contract differs")
    x = features(plans)
    if not set(x["crop"]).issubset(bundle["training_crops"]):
        raise ValueError("A planned crop is absent from the training cohort")
    values = np.maximum(np.asarray(bundle["model"].predict(x), dtype=float), 0)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite plan predictions")
    result = pd.DataFrame({"plan_id": plans.get("plan_id", pd.Series(range(len(plans)), index=plans.index)),
                           "target": bundle["target"], "prediction": values, "unit": bundle["unit"]})
    for name in ["data_kind", "target_assumption", "source_manifest_sha256", "selected_cpu_model"]:
        result[name] = bundle[name]
    result["target_period_confirmed"] = bundle["target_period_confirmed"]
    result["interpretation"] = ("SYNTHETIC RUNTIME DEMO: not farm performance" if
        bundle["data_kind"] == "synthetic_schema_fixture" else "Recorded candidate prediction; not certified cycle total or annual economics")
    return result
