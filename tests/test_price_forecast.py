import numpy as np
import pandas as pd
import pytest

from src.price_forecast import forecast_series, prepare_prices, run_price_experiment


def prices():
    return pd.DataFrame([
        {"crop": "딸기", "variety": "딸기", "grade": "상품", "year_month": f"{year}-{month:02d}",
         "price_krw_per_kg": 1000 + year - 2021 + month * 100, "kg_unit_confirmed": True,
         "unit": "원/1kg", "observation_status": "observed"}
        for year in range(2021, 2026) for month in [1, 2, 3, 12]
    ])


def test_holdout_targets_cannot_change_selection_or_holdout_predictions():
    original = prices()
    first = run_price_experiment(original)
    changed = original.copy()
    changed.loc[changed["year_month"].str.startswith("2025"), "price_krw_per_kg"] *= 10
    second = run_price_experiment(changed)
    assert first["summary"]["series"][0]["selected_model"] == second["summary"]["series"][0]["selected_model"]
    np.testing.assert_array_equal(first["holdout_predictions"]["prediction_krw_per_kg"], second["holdout_predictions"]["prediction_krw_per_kg"])
    assert first["summary"]["holdout_selected"] != second["summary"]["holdout_selected"]


def test_missing_calendar_is_not_zero_filled_or_forecast():
    data = prices()
    data.loc[len(data)] = {**data.iloc[0].to_dict(), "year_month": "2021-06", "price_krw_per_kg": np.nan, "observation_status": "source_dash"}
    result = run_price_experiment(data)
    assert result["summary"]["observed_kg_rows"] == 20
    summer = result["forecast"].loc[result["forecast"]["year_month"].eq("2026-06")].iloc[0]
    assert pd.isna(summer["forecast_krw_per_kg"])
    assert summer["status"] == "no_historical_calendar_support"


def test_explicit_cutoff_prevents_in_year_updates_and_retrodiction():
    data = prepare_prices(prices())
    prediction = forecast_series(data, pd.DatetimeIndex(["2025-01-01", "2025-12-01"]), "seasonal_last", "2024-12-31")
    assert prediction.tolist() == [1103, 2203]
    with pytest.raises(ValueError, match="strictly after"):
        forecast_series(data, pd.DatetimeIndex(["2024-01-01"]), "seasonal_last", "2024-12-31")


@pytest.mark.parametrize("column,value", [("unit", "원/100개"), ("kg_unit_confirmed", False)])
def test_nonkilogram_prices_are_not_silently_converted(column, value):
    data = prices()
    data.loc[0, column] = value
    with pytest.raises(ValueError, match="confirmed"):
        prepare_prices(data)


def test_grades_remain_distinct_and_duplicate_months_are_rejected():
    data = prices()
    other = data.assign(grade="중품", price_krw_per_kg=data["price_krw_per_kg"] / 2)
    result = run_price_experiment(pd.concat([data, other], ignore_index=True))
    assert result["summary"]["series_count"] == 2
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_prices(pd.concat([data, data.iloc[:1]], ignore_index=True))


def test_discontinued_series_without_validation_or_holdout_is_not_fabricated():
    data = prices()
    data = data.loc[data["year_month"].str.startswith("2021")]
    result = run_price_experiment(data)
    summary = result["summary"]["series"][0]
    assert summary["selected_model"] == "seasonal_last"
    assert summary["holdout_selected"]["evaluated_months"] == 0
    assert result["holdout_predictions"].empty
    assert result["forecast"]["forecast_krw_per_kg"].isna().all()
