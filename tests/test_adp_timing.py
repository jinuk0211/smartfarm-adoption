"""Behavior checks for labels, leak prevention, baselines and group separation."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.adp_timing_model import (FEATURES, TARGET, features, grouped_folds,
                                  median_predict, prepare_rows)


def test_whole_bad_cycle_and_unobserved_cycles_are_excluded():
    cultivation = pd.DataFrame({"cycle_id": list("abcde"), "farm_group_id": list("ABCDE"),
                                "crop": ["딸기"] * 4 + ["국화"],
                                "target_crop": [True] * 4 + [False],
                                "planting_date": ["2024-09-01"] * 5})
    quality = cultivation[["cycle_id", "farm_group_id", "crop"]].copy()
    quality["production_record_count"] = [3, 7, 0, 1, 1]
    quality["first_shipment_date"] = ["2024-11-01", "2024-08-31", None, "2024-09-01", "2024-10-01"]
    quality["before_planting_rows"] = [0, 1, 0, 0, 0]
    rows, audit = prepare_rows(cultivation, quality)
    assert rows["cycle_id"].tolist() == ["a", "d"]
    assert rows[TARGET].tolist() == [61, 0]
    assert audit["exclusion_counts"]["no_observed_shipment"] == 1
    assert audit["exclusion_counts"]["any_shipment_before_planting"] == 1


def test_folds_keep_repeated_farm_cycles_together():
    rows = pd.DataFrame({"farm_group_id": np.repeat([f"farm{i}" for i in range(10)], 2)})
    folds = grouped_folds(rows)
    assert sorted(np.concatenate([test for _, test in folds])) == list(range(20))
    for train, test in folds:
        assert set(rows.iloc[train]["farm_group_id"]).isdisjoint(rows.iloc[test]["farm_group_id"])


def test_train_only_medians_and_fallbacks_ignore_query_target():
    train = pd.DataFrame({"crop": ["딸기", "딸기", "오이"], "planting_month": [9, 9, 4],
                          TARGET: [60, 80, 30]})
    query = pd.DataFrame({"crop": ["딸기", "딸기", "신규"], "planting_month": [9, 10, 1],
                          TARGET: [9999, -1, 0]})
    np.testing.assert_array_equal(median_predict(train, query, True), [70, 70, 60])
    query[TARGET] = 1e9
    np.testing.assert_array_equal(median_predict(train, query, True), [70, 70, 60])


def test_feature_allowlist_ignores_all_future_columns():
    rows = pd.DataFrame([{name: (2024 if name == "planting_year" else 9)
                          if name.startswith("planting_") else "sample" for name in FEATURES}])
    rows["source_has_sales"] = "유"
    rows["production_record_count"] = 100
    rows["first_shipment_date"] = "2025-01-01"
    rows[TARGET] = 100
    before = features(rows)
    rows[["source_has_sales", "production_record_count", "first_shipment_date", TARGET]] = "changed"
    pd.testing.assert_frame_equal(features(rows), before)
    assert list(before.columns) == FEATURES
