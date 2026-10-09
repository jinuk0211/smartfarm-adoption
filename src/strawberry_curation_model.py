"""Recorded strawberry crop-cycle kg comparisons, not adoption effects."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

TARGET = "reported_cycle_total_kg"
NUMERIC = ["planting_month", "planting_day", "area_m2"]
CATEGORICAL = ["variety", "region_sido", "region_sigungu", "facility_type",
               "cultivation_method", "greenhouse_type"]
FEATURES = NUMERIC + CATEGORICAL
CLASSICAL = ["global_median", "month_median", "area_scaled_median", "catboost", "xgboost"]
OUTLIER_FLAG = "million_kg_scale_review_no_automatic_correction"
SEED = 42


def prepare_rows(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Use the audited common positive-area cohort without repairing any target."""
    required = FEATURES + [TARGET, "farm_group", "source_record_id", "planting_year",
                           "planting_date", "target_unit", "quality_flags",
                           "target_candidate", "pre_adoption_metadata_eligible"]
    if missing := set(required) - set(candidates.columns):
        raise ValueError(f"Missing curation columns: {sorted(missing)}")
    if candidates["source_record_id"].duplicated().any():
        raise ValueError("Duplicate source record identity")
    if not candidates["target_candidate"].eq(True).all():
        raise ValueError("Candidates contain an ineligible target")
    if not candidates["target_unit"].eq("kg_per_reported_crop_cycle").all():
        raise ValueError("Target unit is not recorded crop-cycle kg")
    included = candidates.loc[candidates["pre_adoption_metadata_eligible"].eq(True)].copy()
    included = included.sort_values("source_record_id").reset_index(drop=True)
    if included.empty or included["farm_group"].isna().any():
        raise ValueError("No eligible rows or missing facility group")
    for column in NUMERIC + [TARGET]:
        included[column] = pd.to_numeric(included[column], errors="raise")
        if not np.isfinite(included[column]).all() or included[column].le(0).any():
            raise ValueError(f"Expected finite positive values: {column}")
    dates = pd.to_datetime(included["planting_date"], errors="raise")
    if not (included["planting_month"].eq(dates.dt.month).all()
            and included["planting_day"].eq(dates.dt.day).all()
            and included["planting_year"].eq(dates.dt.year).all()):
        raise ValueError("Planting date components disagree")
    if included.duplicated(["farm_group", "planting_date"]).any():
        raise ValueError("More than one candidate for a facility planting date")
    included["outlier_review"] = included["quality_flags"].map(
        lambda value: OUTLIER_FLAG in json.loads(value))
    audit = {
        "candidate_rows": len(candidates), "included_rows": len(included),
        "facility_groups": int(included["farm_group"].nunique()),
        "excluded_missing_confirmed_metadata_ids": candidates.loc[
            ~candidates["pre_adoption_metadata_eligible"].eq(True), "source_record_id"].tolist(),
        "planting_year_counts": {str(year): int(count) for year, count in
                                 included["planting_year"].value_counts().sort_index().items()},
        "variety_counts": included["variety"].value_counts().to_dict(),
        "target_min_kg": float(included[TARGET].min()),
        "target_median_kg": float(included[TARGET].median()),
        "target_max_kg": float(included[TARGET].max()),
        "outlier_review_rows": included.loc[included["outlier_review"],
            ["source_record_id", "farm_group", "planting_year", TARGET, "area_m2"]].to_dict("records"),
    }
    return included, audit


def features(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows[FEATURES].copy()
    result[CATEGORICAL] = result[CATEGORICAL].fillna("__missing__").astype(str)
    return result


def assign_folds(rows: pd.DataFrame) -> np.ndarray:
    assignments = np.full(len(rows), -1, dtype=int)
    for number, (train, test) in enumerate(GroupKFold(n_splits=5).split(
            rows, groups=rows["farm_group"])):
        if set(rows.iloc[train]["farm_group"]) & set(rows.iloc[test]["farm_group"]):
            raise ValueError("Facility group leakage")
        if (assignments[test] != -1).any():
            raise ValueError("Repeated held-out row")
        assignments[test] = number
    if (assignments < 0).any():
        raise ValueError("Missing held-out row")
    return assignments


def baselines(train: pd.DataFrame, query: pd.DataFrame) -> dict[str, np.ndarray]:
    global_median = float(train[TARGET].median())
    month_medians = train.groupby("planting_month")[TARGET].median()
    per_area = float((train[TARGET] / train["area_m2"]).median())
    return {
        "global_median": np.full(len(query), global_median),
        "month_median": query["planting_month"].map(month_medians).fillna(global_median).to_numpy(float),
        "area_scaled_median": query["area_m2"].to_numpy(float) * per_area,
    }


def classical_predictions(train: pd.DataFrame, query: pd.DataFrame) -> dict[str, np.ndarray]:
    from catboost import CatBoostRegressor
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder
    from xgboost import XGBRegressor

    x_train, x_query = features(train), features(query)
    result = baselines(train, query)
    cat = CatBoostRegressor(iterations=300, depth=4, learning_rate=0.05, loss_function="MAE",
                           l2_leaf_reg=5, random_seed=SEED, thread_count=2,
                           allow_writing_files=False, verbose=False)
    cat.fit(x_train, train[TARGET], cat_features=CATEGORICAL)
    result["catboost"] = cat.predict(x_query)
    transform = ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("numeric", "passthrough", NUMERIC)])
    encoded_train = transform.fit_transform(x_train)
    encoded_query = transform.transform(x_query)
    xgb = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                       objective="reg:absoluteerror", reg_lambda=5, subsample=0.9,
                       colsample_bytree=1, random_state=SEED, n_jobs=2)
    xgb.fit(encoded_train, train[TARGET])
    result["xgboost"] = xgb.predict(encoded_query)
    return {name: np.maximum(np.asarray(values, dtype=float), 0) for name, values in result.items()}


def summarize_predictions(oof: pd.DataFrame, model_names: list[str]) -> dict:
    def score(rows: pd.DataFrame, name: str) -> dict:
        actual, predicted = rows[TARGET].to_numpy(float), rows[name].to_numpy(float)
        if not np.isfinite(predicted).all() or not len(rows):
            raise ValueError(f"Missing or nonfinite OOF predictions: {name}")
        error = predicted - actual
        return {"n_scored": len(rows), "mae_kg": float(np.abs(error).mean()),
                "rmse_kg": float(np.sqrt(np.square(error).mean())),
                "median_absolute_error_kg": float(np.median(np.abs(error)))}

    return {name: {**score(oof, name),
                   "by_fold": {str(fold): score(rows, name) for fold, rows in oof.groupby("fold")}}
            for name in model_names}
