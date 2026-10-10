"""Cutoff-safe monthly wholesale-price experiments; never a farmgate quote."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

SERIES = ["crop", "variety", "grade"]
TARGET = "price_krw_per_kg"
MODELS = ("seasonal_last", "seasonal_median", "seasonal_ridge")


def prepare_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Retain only observed, explicitly confirmed kilogram prices, with no fill."""
    required = SERIES + [TARGET, "year_month", "kg_unit_confirmed", "observation_status", "unit"]
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing price columns: {sorted(missing)}")
    data = frame.copy()
    confirmed = data["kg_unit_confirmed"].astype(str).str.lower().eq("true")
    if not confirmed.all() or not data["unit"].eq("원/1kg").all():
        raise ValueError("Use only the explicitly confirmed 원/1kg source table; no inferred conversion")
    data["date"] = pd.to_datetime(data["year_month"], format="%Y-%m", errors="raise")
    if data.duplicated(SERIES + ["date"]).any():
        raise ValueError("Duplicate monthly observations within crop, variety and grade")
    data[TARGET] = pd.to_numeric(data[TARGET], errors="raise")
    data = data.loc[data["observation_status"].eq("observed")].copy()
    if data[TARGET].isna().any() or not np.isfinite(data[TARGET]).all() or (data[TARGET] <= 0).any():
        raise ValueError("Observed kilogram prices must be finite and positive")
    data["year"] = data["date"].dt.year
    data["month"] = data["date"].dt.month
    return data.sort_values(SERIES + ["date"]).reset_index(drop=True)


def _features(dates: pd.DatetimeIndex, origin_year: int) -> np.ndarray:
    months = np.eye(12)[dates.month - 1]
    return np.column_stack([months, dates.year - origin_year])


def forecast_series(
    history: pd.DataFrame, dates: pd.DatetimeIndex, model: str, cutoff: str,
) -> np.ndarray:
    """Make one fixed-origin batch forecast. Unseen calendar months stay missing."""
    if model not in MODELS:
        raise ValueError(f"Unknown model: {model}")
    cutoff_date = pd.Timestamp(cutoff)
    if len(dates) and (dates <= cutoff_date).any():
        raise ValueError("Forecast dates must be strictly after the training cutoff")
    train = history.loc[history["date"] <= cutoff_date].sort_values("date")
    predictions = np.full(len(dates), np.nan)
    if train.empty:
        return predictions
    calendar = set(train["month"])
    supported = np.array([month in calendar for month in dates.month], dtype=bool)
    if model == "seasonal_ridge":
        # Fixed hyperparameter; only model family is selected on validation MAE.
        origin = int(train["year"].min())
        regressor = Ridge(alpha=1.0)
        regressor.fit(_features(pd.DatetimeIndex(train["date"]), origin), np.log(train[TARGET]))
        if supported.any():
            predictions[supported] = np.exp(regressor.predict(_features(dates[supported], origin)))
    else:
        for index, date in enumerate(dates):
            month = train.loc[train["month"].eq(date.month), TARGET]
            if len(month):
                predictions[index] = float(month.iloc[-1] if model == "seasonal_last" else month.median())
    return predictions


def _metrics(rows: pd.DataFrame, prediction: str = "prediction_krw_per_kg") -> dict[str, Any]:
    if rows.empty:
        return {"evaluated_months": 0, "mae_krw_per_kg": None, "wape_percent": None}
    valid = rows.dropna(subset=["actual_krw_per_kg", prediction])
    if valid.empty:
        return {"evaluated_months": 0, "mae_krw_per_kg": None, "wape_percent": None}
    error = (valid["actual_krw_per_kg"] - valid[prediction]).abs()
    return {"evaluated_months": len(valid), "mae_krw_per_kg": float(error.mean()),
            "wape_percent": float(100 * error.sum() / valid["actual_krw_per_kg"].sum())}


def run_price_experiment(frame: pd.DataFrame) -> dict[str, Any]:
    """Select on 2024, score 2025 once, and refit through 2025 for 2026 forecasts."""
    data = prepare_prices(frame)
    if not set(data["year"]).issubset({2021, 2022, 2023, 2024, 2025}):
        raise ValueError("This registered experiment uses only the 2021–2025 snapshot")
    validation_rows, holdout_rows, future_rows, series_summaries = [], [], [], []
    for key, group in data.groupby(SERIES, sort=True):
        identity = dict(zip(SERIES, key))
        validation = group.loc[group["year"].eq(2024)]
        scores = {}
        for model in MODELS:
            predictions = forecast_series(group, pd.DatetimeIndex(validation["date"]), model, "2023-12-31")
            rows = [{**identity, "model": model, "year_month": date.strftime("%Y-%m"),
                     "actual_krw_per_kg": float(actual), "prediction_krw_per_kg": float(prediction)}
                    for date, actual, prediction in zip(validation["date"], validation[TARGET], predictions)]
            validation_rows.extend(rows)
            measured = _metrics(pd.DataFrame(rows, columns=["actual_krw_per_kg", "prediction_krw_per_kg"]))
            scores[model] = measured
        eligible = [model for model in MODELS if scores[model]["evaluated_months"] >= 2]
        selected = min(eligible, key=lambda model: scores[model]["mae_krw_per_kg"]) if eligible else MODELS[0]
        holdout = group.loc[group["year"].eq(2025)]
        dates = pd.DatetimeIndex(holdout["date"])
        selected_predictions = forecast_series(group, dates, selected, "2024-12-31")
        baseline_predictions = forecast_series(group, dates, MODELS[0], "2024-12-31")
        rows = [{**identity, "selected_model": selected, "year_month": date.strftime("%Y-%m"),
                 "actual_krw_per_kg": float(actual), "prediction_krw_per_kg": float(prediction),
                 "baseline_krw_per_kg": float(baseline)}
                for date, actual, prediction, baseline in zip(holdout["date"], holdout[TARGET], selected_predictions, baseline_predictions)]
        holdout_rows.extend(rows)
        held = pd.DataFrame(rows, columns=SERIES + ["selected_model", "year_month", "actual_krw_per_kg", "prediction_krw_per_kg", "baseline_krw_per_kg"])
        future_dates = pd.date_range("2026-01-01", periods=12, freq="MS")
        future = forecast_series(group, future_dates, selected, "2025-12-31")
        future_baseline = forecast_series(group, future_dates, MODELS[0], "2025-12-31")
        for date, prediction, baseline in zip(future_dates, future, future_baseline):
            month_history = group.loc[group["month"].eq(date.month)]
            status = "forecast"
            if not (group["year"] == 2025).any():
                status = "inactive_series_no_2025_observation"
            elif month_history.empty:
                status = "no_historical_calendar_support"
            elif not (month_history["year"] >= 2024).any():
                status = "no_recent_calendar_support"
            if status != "forecast":
                prediction = float("nan")
                baseline = float("nan")
            future_rows.append({**identity, "selected_model": selected,
                                "year_month": date.strftime("%Y-%m"), "cutoff": "2025-12-31",
                                "forecast_krw_per_kg": float(prediction),
                                "baseline_forecast_krw_per_kg": float(baseline),
                                "observed_training_years_for_month": len(month_history),
                                "status": status})
        series_summaries.append({**identity, "observed_months": len(group), "selected_model": selected,
                                 "validation": scores, "holdout_selected": _metrics(held),
                                 "holdout_baseline": _metrics(held, "baseline_krw_per_kg")})
    held = pd.DataFrame(holdout_rows)
    summary = {
        "source": "KAMIS 중도매인 판매가격; 전체지역 공개조회; 상품/중품 별도",
        "target": "monthly KRW per kg, not farmgate revenue",
        "raw_calendar_rows": len(frame), "observed_kg_rows": len(data), "series_count": len(series_summaries),
        "split": {"initial_train": "2021–2023", "model_selection": "2024", "untouched_holdout": "2025",
                  "holdout_training_cutoff": "2024-12-31", "forecast_training_cutoff": "2025-12-31", "forecast_calendar": "2026-01–2026-12"},
        "holdout_selected": _metrics(held), "holdout_baseline": _metrics(held, "baseline_krw_per_kg"),
        "series": series_summaries,
        "limitations": ["No future fill; source dash and unlisted months are excluded, not treated as zero.",
                        "All 12 holdout months use a fixed 2024-12-31 origin; no in-year holdout updates.",
                        "Forecasts require a 2025 observation for the series and a 2024/2025 observation for the calendar month; supported months may still have no future trading.",
                        "The 2026 curve is a retrospective forecast from the archived 2025 cutoff, not a current-date or validated 2026 forecast.",
                        "Wholesale/intermediary prices must not replace farmgate prices without a verified margin/channel mapping.",
                        "No prediction intervals or causal weather/equipment effects are estimated.",
                        "Pooled MAE mixes crops with different price scales; inspect each series too."],
    }
    return {"summary": summary, "validation_predictions": pd.DataFrame(validation_rows),
            "holdout_predictions": held, "forecast": pd.DataFrame(future_rows)}
