"""Facility-group comparisons of recorded cycle gross sales, not farm profit."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

TARGET = "revenue_krw_per_cycle"
CATEGORICAL = ["crop", "cultivar", "province", "district", "facility_type"]
NUMERIC = ["planting_year", "planting_month"]
FEATURES = CATEGORICAL + NUMERIC
CLASSICAL = ["crop_median", "crop_month_median", "catboost", "xgboost"]
SEED = 42


def prepare_rows(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = FEATURES + [TARGET, "source_row_id", "cycle_id", "facility_id", "large_revenue_review_flag"]
    if missing := set(required) - set(candidates.columns):
        raise ValueError(f"Missing regional columns: {sorted(missing)}")
    rows = candidates.copy().sort_values("source_row_id").reset_index(drop=True)
    if rows.empty or rows["source_row_id"].duplicated().any() or rows["cycle_id"].duplicated().any():
        raise ValueError("Empty or duplicate regional candidate identities")
    if rows["facility_id"].isna().any() or rows["facility_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Missing facility identity")
    for name in NUMERIC + [TARGET]:
        rows[name] = pd.to_numeric(rows[name], errors="raise")
        if not np.isfinite(rows[name]).all() or rows[name].le(0).any():
            raise ValueError(f"Expected finite positive values: {name}")
    if not rows["planting_month"].between(1, 12).all():
        raise ValueError("Invalid planting month")
    if not rows["large_revenue_review_flag"].isin([True, False]).all():
        raise ValueError("Invalid review flag")
    if not rows["large_revenue_review_flag"].eq(rows[TARGET].gt(10_000_000_000)).all():
        raise ValueError("Review flag differs from declared preparation threshold")
    audit = {"included_rows": len(rows), "facility_groups": int(rows["facility_id"].nunique()),
             "crop_counts": rows["crop"].value_counts().to_dict(),
             "planting_year_counts": {str(year): int(count) for year, count in rows["planting_year"].value_counts().sort_index().items()},
             "target_min_krw": float(rows[TARGET].min()), "target_median_krw": float(rows[TARGET].median()),
             "target_max_krw": float(rows[TARGET].max()),
             "outlier_review_rows": rows.loc[rows["large_revenue_review_flag"],
                 ["source_row_id", "facility_id", "crop", TARGET]].to_dict("records")}
    return rows, audit


def features(rows: pd.DataFrame) -> pd.DataFrame:
    values = rows[FEATURES].copy()
    values[CATEGORICAL] = values[CATEGORICAL].fillna("__missing__").astype(str)
    return values


def assign_folds(rows: pd.DataFrame) -> np.ndarray:
    assignments = np.full(len(rows), -1, dtype=int)
    for number, (train, query) in enumerate(GroupKFold(n_splits=5).split(rows, groups=rows["facility_id"])):
        if set(rows.iloc[train]["facility_id"]) & set(rows.iloc[query]["facility_id"]):
            raise ValueError("Facility group leakage")
        if (assignments[query] != -1).any():
            raise ValueError("Repeated held-out row")
        assignments[query] = number
    if (assignments < 0).any():
        raise ValueError("Missing held-out row")
    return assignments


def baselines(train: pd.DataFrame, query: pd.DataFrame) -> dict[str, np.ndarray]:
    crop = train.groupby("crop")[TARGET].median()
    month = train.groupby(["crop", "planting_month"])[TARGET].median()
    ordinary = query["crop"].map(crop).fillna(train[TARGET].median()).to_numpy(float)
    specific = np.array([month.get((row.crop, row.planting_month), np.nan)
                         for row in query.itertuples()], dtype=float)
    return {"crop_median": ordinary, "crop_month_median": np.where(np.isfinite(specific), specific, ordinary)}


def classical_predictions(train: pd.DataFrame, query: pd.DataFrame) -> dict[str, np.ndarray]:
    from catboost import CatBoostRegressor
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder
    from xgboost import XGBRegressor

    x_train, x_query = features(train), features(query)
    results = baselines(train, query)
    cat = CatBoostRegressor(iterations=300, depth=4, learning_rate=0.05, loss_function="MAE",
                           l2_leaf_reg=5, random_seed=SEED, thread_count=2,
                           allow_writing_files=False, verbose=False)
    cat.fit(x_train, train[TARGET], cat_features=CATEGORICAL)
    results["catboost"] = cat.predict(x_query)
    transform = ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ("numeric", "passthrough", NUMERIC)])
    encoded_train, encoded_query = transform.fit_transform(x_train), transform.transform(x_query)
    xgb = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                       objective="reg:absoluteerror", reg_lambda=5, subsample=0.9,
                       colsample_bytree=1, random_state=SEED, n_jobs=2)
    xgb.fit(encoded_train, train[TARGET])
    results["xgboost"] = xgb.predict(encoded_query)
    return {name: np.maximum(np.asarray(values, dtype=float), 0) for name, values in results.items()}


def summarize_predictions(oof: pd.DataFrame, model_names: list[str]) -> dict:
    def score(rows, name):
        predicted = rows[name].to_numpy(float)
        if not len(rows) or not np.isfinite(predicted).all():
            raise ValueError(f"Missing or nonfinite OOF predictions: {name}")
        error = predicted - rows[TARGET].to_numpy(float)
        return {"n_scored": len(rows), "mae_krw": float(np.abs(error).mean()),
                "rmse_krw": float(np.sqrt(np.square(error).mean())),
                "median_absolute_error_krw": float(np.median(np.abs(error)))}
    return {name: {**score(oof, name),
                   "by_crop": {str(crop): score(group, name) for crop, group in oof.groupby("crop")},
                   "by_fold": {str(fold): score(group, name) for fold, group in oof.groupby("fold")}}
            for name in model_names}
