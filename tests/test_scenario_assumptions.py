import pandas as pd
import pytest

from src.scenario_assumptions import relative_market_price


def frames():
    keys = {"crop": "딸기", "variety": "설향", "grade": "상품"}
    old = pd.DataFrame([{**keys, "year_month": "2025-01", "actual_krw_per_kg": 100},
                        {**keys, "year_month": "2025-02", "actual_krw_per_kg": 200}])
    new = pd.DataFrame([{**keys, "year_month": "2026-01", "cutoff": "2025-12-31", "baseline_forecast_krw_per_kg": 200},
                        {**keys, "year_month": "2026-02", "cutoff": "2025-12-31", "baseline_forecast_krw_per_kg": 250}])
    return old, new, keys


def test_relative_change_is_ratio_of_same_month_prices_not_direct_price():
    old, new, keys = frames()
    result = relative_market_price(old, new, **keys, months=[1, 2])
    assert result["factor"] == 1.5
    assert result["forecast_origin"] == "2025-12-31"
    assert len(result["comparison"]) == 2


@pytest.mark.parametrize("months", [[], [1, 1], [0], [True], [1, 3]])
def test_missing_or_invalid_selected_month_is_not_silently_skipped(months):
    old, new, keys = frames()
    with pytest.raises(ValueError):
        relative_market_price(old, new, **keys, months=months)


def test_mismatched_forecast_origin_or_duplicate_series_rejected():
    old, new, keys = frames()
    new.loc[0, "cutoff"] = "2024-12-31"
    with pytest.raises(ValueError):
        relative_market_price(old, new, **keys, months=[1])
    old, new, keys = frames()
    with pytest.raises(ValueError):
        relative_market_price(pd.concat([old, old]), new, **keys, months=[1])
