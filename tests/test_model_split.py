import numpy as np
import pandas as pd

from src.smartfarm_model import FEATURES, baseline_predict, build_features, chronological_split


def test_all_test_rows_are_later_than_all_training_rows():
    records = pd.DataFrame({"year": [2020, 2021, 2022, 2022], "crop": ["딸기"] * 4})
    train, test, cutoff = chronological_split(records)
    assert cutoff == 2022
    assert train["year"].max() < test["year"].min()
    assert len(test) == 2


def test_target_derived_and_post_adoption_fields_cannot_enter_features():
    record = pd.DataFrame([{
        "year": 2024, "crop": "딸기", "cultivation_type": "수경", "region": "경북",
        "yield_kg_per_1000m2": 1, "revenue_krw_per_1000m2": 999,
        "farmgate_price_krw_per_kg": 999, "actual_humidity": 40,
    }])
    assert build_features(record).columns.tolist() == FEATURES
    assert not set(build_features(record).columns) & {"yield_kg_per_1000m2", "revenue_krw_per_1000m2", "farmgate_price_krw_per_kg", "actual_humidity"}


def test_baseline_excludes_future_year_and_incompatible_source_category():
    history = pd.DataFrame([
        {"year": 2023, "crop": "딸기", "cultivation_type": "수경", "region": "경북", "source_category": "시설딸기수경", "yield_kg_per_1000m2": 100},
        {"year": 2024, "crop": "딸기", "cultivation_type": "수경", "region": "경북", "source_category": "시설딸기수경", "yield_kg_per_1000m2": 9999},
        {"year": 2022, "crop": "딸기", "cultivation_type": "수경", "region": "경북", "source_category": "촉성", "yield_kg_per_1000m2": 9999},
    ])
    query = pd.DataFrame([{"year": 2024, "crop": "딸기", "cultivation_type": "수경", "region": "경북", "source_category": "시설딸기수경"}])
    assert baseline_predict(history, query)[0] == 100
    query.loc[0, "region"] = "전북"
    assert np.isnan(baseline_predict(history, query)[0])
    query.loc[0, "region"] = "경북"
    query.loc[0, "crop"] = "오이"
    assert np.isnan(baseline_predict(history, query)[0])
