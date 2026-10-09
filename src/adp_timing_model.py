"""Exploratory recorded-shipment timing; not first harvest or farm economics."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

TARGET = "days_to_first_recorded_shipment"
CATEGORICAL = ["crop", "province", "city", "greenhouse_material", "greenhouse_structure", "variety"]
NUMERIC = ["planting_year", "planting_month"]
FEATURES = NUMERIC + CATEGORICAL
TARGET_CROPS = {"딸기", "오이", "완숙토마토", "방울토마토", "파프리카"}
SEED = 42


def prepare_rows(cultivation: pd.DataFrame, quality: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Join one cycle once and exclude whole cycles with any pre-planting record."""
    quality_columns = ["cycle_id", "farm_group_id", "crop", "production_record_count",
                       "first_shipment_date", "before_planting_rows"]
    data = cultivation.merge(quality[quality_columns], on="cycle_id", how="left",
                             suffixes=("", "_quality"), validate="one_to_one", indicator=True)
    if not data["_merge"].eq("both").all():
        raise ValueError("A cultivation cycle has no quality audit")
    for name in ["farm_group_id", "crop"]:
        if not data[name].eq(data[name + "_quality"]).all():
            raise ValueError(f"Cultivation/quality identity mismatch: {name}")
    if data["farm_group_id"].isna().any():
        raise ValueError("Missing farm group")
    data["planting_date"] = pd.to_datetime(data["planting_date"], errors="raise")
    data["first_shipment_date"] = pd.to_datetime(data["first_shipment_date"], errors="raise")
    data[TARGET] = (data["first_shipment_date"] - data["planting_date"]).dt.days
    target_crop = data["crop"].isin(TARGET_CROPS)
    if not data["target_crop"].eq(target_crop).all():
        raise ValueError("Unexpected target_crop membership")
    reasons = np.select(
        [~target_crop, data["planting_date"].isna(),
         data["production_record_count"].eq(0) | data["first_shipment_date"].isna(),
         data["before_planting_rows"].gt(0), data[TARGET].lt(0)],
        ["outside_target_crops", "missing_planting_date", "no_observed_shipment",
         "any_shipment_before_planting", "negative_date_interval"], default="included")
    data["exclusion_reason"] = reasons
    included = data.loc[data["exclusion_reason"].eq("included")].copy()
    included = included.sort_values("cycle_id").reset_index(drop=True)
    included["planting_year"] = included["planting_date"].dt.year.astype(int)
    included["planting_month"] = included["planting_date"].dt.month.astype(int)
    audit = {"n_source_cycles": len(data), "n_target_crop_cycles": int(target_crop.sum()),
             "n_included": len(included), "n_farm_groups": included["farm_group_id"].nunique(),
             "exclusion_counts": data["exclusion_reason"].value_counts().to_dict(),
             "by_crop": included.groupby("crop").agg(
                 n_rows=("cycle_id", "size"), n_groups=("farm_group_id", "nunique"),
                 target_min_days=(TARGET, "min"), target_median_days=(TARGET, "median"),
                 target_max_days=(TARGET, "max")).reset_index().to_dict("records"),
             "excluded_cycles": data.loc[~data["exclusion_reason"].eq("included"),
                                         ["cycle_id", "crop", "exclusion_reason"]].to_dict("records")}
    return included, audit


def features(rows: pd.DataFrame) -> pd.DataFrame:
    """A fixed allowlist prevents dates/outcome coverage flags from leaking in."""
    result = rows[FEATURES].copy()
    result[CATEGORICAL] = result[CATEGORICAL].fillna("__missing__").astype(str)
    return result


def grouped_folds(rows: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    folds = list(GroupKFold(n_splits=5).split(rows, groups=rows["farm_group_id"]))
    seen = np.zeros(len(rows), dtype=int)
    for train, test in folds:
        if set(rows.iloc[train]["farm_group_id"]) & set(rows.iloc[test]["farm_group_id"]):
            raise ValueError("Farm group leakage")
        seen[test] += 1
    if not np.all(seen == 1):
        raise ValueError("Each row must receive exactly one OOF prediction")
    return folds


def median_predict(train: pd.DataFrame, query: pd.DataFrame, by_month: bool) -> np.ndarray:
    """Fit medians on training labels only; month -> crop -> global fallback."""
    crop_medians = train.groupby("crop")[TARGET].median()
    predicted = query["crop"].map(crop_medians).fillna(train[TARGET].median()).to_numpy(float)
    if by_month:
        month_medians = train.groupby(["crop", "planting_month"])[TARGET].median()
        specific = np.array([month_medians.get((row.crop, row.planting_month), np.nan)
                             for row in query.itertuples()], dtype=float)
        predicted = np.where(np.isfinite(specific), specific, predicted)
    return predicted


def classical_predictions(train: pd.DataFrame, query: pd.DataFrame) -> dict[str, np.ndarray]:
    from catboost import CatBoostRegressor
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder
    from xgboost import XGBRegressor

    x_train, x_query = features(train), features(query)
    result = {"crop_median": median_predict(train, query, False),
              "crop_month_median": median_predict(train, query, True)}
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
    return {name: np.maximum(values, 0) for name, values in result.items()}


def summarize_predictions(oof: pd.DataFrame, model_names: list[str]) -> dict:
    def score(rows: pd.DataFrame, name: str) -> dict:
        values = rows[name].to_numpy(float)
        if not np.isfinite(values).all():
            raise ValueError(f"Missing or nonfinite OOF predictions: {name}")
        error = values - rows[TARGET].to_numpy(float)
        return {"n_scored": len(rows), "mae_days": float(np.mean(np.abs(error))),
                "rmse_days": float(np.sqrt(np.mean(error ** 2)))}

    return {name: {**score(oof, name),
                   "by_crop": {str(crop): score(rows, name) for crop, rows in oof.groupby("crop")},
                   "by_fold": {str(fold): score(rows, name) for fold, rows in oof.groupby("fold")}}
            for name in model_names}
