"""Explicit transfer assumptions between market/weather references and a plan."""

from __future__ import annotations

import math

import pandas as pd


def relative_market_price(holdout: pd.DataFrame, forecast: pd.DataFrame, *, crop: str,
                          variety: str, grade: str, months: list[int],
                          method: str = "baseline_forecast_krw_per_kg") -> dict:
    """Ratio of equal-month mean prices; all requested months must be observed.

    This is a user-chosen transfer of market relative change, not a mapping of
    wholesale price levels to farmgate prices or a current-date forecast.
    """
    allowed = {"baseline_forecast_krw_per_kg", "forecast_krw_per_kg"}
    if method not in allowed:
        raise ValueError("Unknown price method")
    if not months or len(set(months)) != len(months) or any(type(month) is not int or not 1 <= month <= 12 for month in months):
        raise ValueError("Select unique calendar months from 1 to 12")
    subsets = []
    for frame in [holdout, forecast]:
        subset = frame.loc[(frame.crop == crop) & (frame.variety == variety) & (frame.grade == grade)].copy()
        if subset.year_month.duplicated().any():
            raise ValueError("Ambiguous price series")
        subsets.append(subset.set_index("year_month"))
    observed, future = subsets
    if future.empty or set(future.cutoff) != {"2025-12-31"}:
        raise ValueError("Expected the archived 2025-12-31 forecast origin")
    comparison = []
    for month in sorted(months):
        actual = observed["actual_krw_per_kg"].get(f"2025-{month:02d}")
        estimate = future[method].get(f"2026-{month:02d}")
        if any(value is None or not math.isfinite(float(value)) or float(value) <= 0 for value in [actual, estimate]):
            raise ValueError(f"{month}월의 실제값 또는 전망이 없어 상대 변화를 적용할 수 없습니다")
        comparison.append({"month": month, "actual_2025_krw_per_kg": float(actual), "forecast_2026_krw_per_kg": float(estimate)})
    actual_mean = sum(row["actual_2025_krw_per_kg"] for row in comparison) / len(comparison)
    forecast_mean = sum(row["forecast_2026_krw_per_kg"] for row in comparison) / len(comparison)
    return {"factor": forecast_mean / actual_mean, "crop": crop, "variety": variety, "grade": grade,
            "method": method, "comparison": comparison, "actual_mean_krw_per_kg": actual_mean,
            "forecast_mean_krw_per_kg": forecast_mean,
            "weighting": "Equal monthly weights, equivalent to assumed equal sold kg across chosen months",
            "forecast_origin": "2025-12-31", "forecast_year": 2026,
            "interpretation": "User-chosen relative-change transfer to farmgate reference; not direct wholesale pricing or a current forecast"}
