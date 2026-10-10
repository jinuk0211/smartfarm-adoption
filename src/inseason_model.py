"""Retrospective, in-season strawberry visit prediction; never adoption inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

GROWTH = {"초장": ("height_mm", "mm"), "엽수": ("leaf_count", "개"),
          "엽장": ("leaf_length_mm", "mm"), "엽폭": ("leaf_width_mm", "mm"),
          "관부직경": ("crown_diameter_mm", "mm")}
ENVIRONMENT = {"내부일평균온도": ("temperature_c", "°C"),
               "내부평균습도": ("humidity_pct", "%"), "CO2농도": ("co2_ppm", "ppm")}
GROWTH_FEATURES = [value[0] for value in GROWTH.values()] + [
    "day_of_year", "days_after_planting", "previous_visit_gap_days", "previous_height_delta_mm"]
ENVIRONMENT_FEATURES = [f"{name}_{window}d_{stat}"
                        for name, _ in ENVIRONMENT.values()
                        for window in (7, 28) for stat in ("mean", "min", "max", "count")]
FEATURES = GROWTH_FEATURES + ENVIRONMENT_FEATURES
TARGET = "next_visit_height_mm"
MODELS = ["current_height", "catboost_growth", "catboost_growth_environment",
          "xgboost_growth_environment"]


def build_cohort(growth: pd.DataFrame, environment: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Use exact seven-day visits, unique containing cycle, and strictly prior days.

    Different sample numbers are not presumed to identify the same plant over time.
    The target is the next visit's observed sample mean, not individual plant growth.
    """
    g = growth.copy()
    g["date"] = pd.to_datetime(g["조사일자"], errors="coerce").dt.normalize()
    g["value"] = pd.to_numeric(g["측정값"], errors="coerce")
    valid_unit = pd.Series(False, index=g.index)
    for item, (_, unit) in GROWTH.items():
        valid_unit |= g["항목명"].eq(item) & g["단위"].eq(unit)
    valid = valid_unit & np.isfinite(g["value"]) & g["value"].ge(0) & g["date"].notna()
    valid &= g["시설ID"].notna() & g["표본번호"].notna() & g["품목"].eq("딸기")
    valid &= ~g["항목명"].eq("초장") | g["value"].gt(0)
    g = g.loc[valid].copy()
    sample_key = ["시설ID", "date", "표본번호", "항목명"]
    g = g.drop_duplicates(sample_key + ["value"])
    conflicts = g.duplicated(sample_key, keep=False)
    conflict_count = int(conflicts.sum())
    g = g.loc[~conflicts]
    visits = g.pivot_table(index=["시설ID", "date"], columns="항목명", values="value", aggfunc="mean")
    visits = visits.rename(columns={key: value[0] for key, value in GROWTH.items()})
    visits = visits.reindex(columns=[value[0] for value in GROWTH.values()]).reset_index()
    visits = visits.dropna(subset=["height_mm"])

    e = environment.loc[environment["품목"].eq("딸기")].copy()
    e["start"] = pd.to_datetime(e["정식시작일"], errors="coerce").dt.normalize()
    e["end"] = pd.to_datetime(e["정식종료일"], errors="coerce").dt.normalize()
    e["date"] = pd.to_datetime(e["분석일자"], errors="coerce").dt.normalize()
    valid_cycle = e["start"].notna() & e["end"].notna() & e["start"].le(e["end"])
    e = e.loc[valid_cycle & e["시설ID"].notna()].copy()
    cycles = e[["시설ID", "start", "end"]].drop_duplicates()
    for column, (name, _) in ENVIRONMENT.items():
        e[name] = pd.to_numeric(e[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    env_names = [value[0] for value in ENVIRONMENT.values()]
    env_key = ["시설ID", "start", "end", "date"]
    e = e.loc[e["date"].between(e["start"], e["end"])].drop_duplicates(env_key + env_names)
    env_conflicts = e.duplicated(env_key, keep=False)
    env_conflict_count = int(env_conflicts.sum())
    e = e.loc[~env_conflicts]

    matched = []
    unmatched = ambiguous = 0
    for _, visit in visits.iterrows():
        match = cycles.loc[cycles["시설ID"].eq(visit["시설ID"])
                           & cycles["start"].le(visit["date"]) & cycles["end"].ge(visit["date"])]
        if len(match) != 1:
            unmatched += len(match) == 0
            ambiguous += len(match) > 1
            continue
        item = visit.to_dict()
        item.update(match.iloc[0][["start", "end"]].to_dict())
        matched.append(item)
    if not matched:
        raise ValueError("No visits have a unique matching crop cycle")
    visits = pd.DataFrame(matched).sort_values(["시설ID", "start", "date"])
    cycle_key = ["시설ID", "start", "end"]
    grouped = visits.groupby(cycle_key, sort=False)
    visits["next_date"] = grouped["date"].shift(-1)
    visits[TARGET] = grouped["height_mm"].shift(-1)
    visits["previous_visit_gap_days"] = (visits["date"] - grouped["date"].shift(1)).dt.days
    visits["previous_height_delta_mm"] = visits["height_mm"] - grouped["height_mm"].shift(1)
    visits["day_of_year"] = visits["date"].dt.dayofyear
    visits["days_after_planting"] = (visits["date"] - visits["start"]).dt.days
    rows = visits.loc[(visits["next_date"] - visits["date"]).dt.days.eq(7)].copy()
    if rows.empty:
        raise ValueError("No exact seven-day visit pairs in a unique crop cycle")
    for index, visit in rows.iterrows():
        past = e.loc[e["시설ID"].eq(visit["시설ID"]) & e["start"].eq(visit["start"])
                     & e["end"].eq(visit["end"]) & e["date"].lt(visit["date"])]
        for window in (7, 28):
            interval = past.loc[past["date"].ge(visit["date"] - pd.Timedelta(days=window))]
            for name in env_names:
                for stat in ("mean", "min", "max", "count"):
                    rows.loc[index, f"{name}_{window}d_{stat}"] = getattr(interval[name], stat)()
    audit = {
        "growth_raw_rows": len(growth), "environment_raw_rows": len(environment),
        "height_raw_rows_mm": int((growth["항목명"].eq("초장") & growth["단위"].eq("mm")).sum()),
        "height_visits": len(matched) + unmatched + ambiguous,
        "visits_without_cycle": int(unmatched), "visits_ambiguous_cycle": int(ambiguous),
        "conflicting_growth_sample_rows_excluded": conflict_count,
        "conflicting_environment_day_rows_excluded": env_conflict_count,
        "exact_seven_day_pairs": len(rows),
        "pairs_with_prior_temperature_28d": int(rows["temperature_c_28d_count"].gt(0).sum()),
        "facilities": int(rows["시설ID"].nunique()),
        "temperature_days_28d_min": float(rows["temperature_c_28d_count"].min()),
        "temperature_days_28d_median": float(rows["temperature_c_28d_count"].median()),
        "temperature_days_28d_max": float(rows["temperature_c_28d_count"].max()),
        "height_unit": "mm", "horizon_days": 7,
    }
    rows["farm_group"] = rows["시설ID"]
    return rows.reset_index(drop=True), audit


def evaluate(rows: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    """Fixed small models and facility-disjoint folds; no holdout-based tuning."""
    from catboost import CatBoostRegressor
    from xgboost import XGBRegressor

    rows = rows.reset_index(drop=True)
    count = rows["farm_group"].nunique()
    if count < 2:
        raise ValueError("At least two facilities are needed for held-out evaluation")
    output = rows.copy()
    output["fold"] = -1
    for model in MODELS:
        output[model] = np.nan
    folds = GroupKFold(n_splits=min(5, count))
    for fold, (train_index, test_index) in enumerate(folds.split(rows, groups=rows["farm_group"])):
        train, test = rows.iloc[train_index], rows.iloc[test_index]
        if set(train["farm_group"]) & set(test["farm_group"]):
            raise ValueError("Facility leakage")
        output.loc[test_index, "fold"] = fold
        output.loc[test_index, "current_height"] = test["height_mm"].to_numpy()
        target_delta = train[TARGET] - train["height_mm"]
        for name, columns in [("catboost_growth", GROWTH_FEATURES),
                              ("catboost_growth_environment", FEATURES)]:
            model = CatBoostRegressor(iterations=120, depth=2, learning_rate=0.05,
                                      loss_function="MAE", l2_leaf_reg=5, random_seed=42,
                                      thread_count=2, allow_writing_files=False, verbose=False)
            model.fit(train[columns], target_delta)
            output.loc[test_index, name] = np.maximum(0, test["height_mm"] + model.predict(test[columns]))
        model = XGBRegressor(n_estimators=120, max_depth=2, learning_rate=0.05,
                             objective="reg:absoluteerror", reg_lambda=5,
                             random_state=42, n_jobs=2)
        model.fit(train[FEATURES], target_delta)
        output.loc[test_index, "xgboost_growth_environment"] = np.maximum(
            0, test["height_mm"] + model.predict(test[FEATURES]))
    metrics = []
    for name in MODELS:
        error = output[name] - output[TARGET]
        if not np.isfinite(error).all() or output["fold"].lt(0).any():
            raise ValueError("Incomplete out-of-fold predictions")
        metrics.append({"model": name, "mae_mm": float(error.abs().mean()),
                        "rmse_mm": float(np.sqrt(np.square(error).mean())),
                        "median_absolute_error_mm": float(error.abs().median()),
                        "n_scored": len(output),
                        "fold_mae_mm": {str(fold): float(part.abs().mean())
                                        for fold, part in error.groupby(output["fold"])}})
    return metrics, output
