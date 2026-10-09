"""Checks for actual cohort, feature leakage, facility separation and baselines."""

import json

import numpy as np
import pandas as pd
import pytest

from src.strawberry_curation_model import (FEATURES, OUTLIER_FLAG, TARGET, assign_folds,
                                         baselines, features, prepare_rows, summarize_predictions)


def candidates():
    rows = pd.DataFrame([{name: "known" for name in FEATURES} for _ in range(11)])
    rows["source_record_id"] = [f"source:{i}" for i in range(11)]
    rows["farm_group"] = [f"farm:{i // 2}" for i in range(11)]
    rows["planting_date"] = [f"{2020 + i % 2}-09-01" for i in range(11)]
    rows["planting_year"] = [2020 + i % 2 for i in range(11)]
    rows["planting_month"], rows["planting_day"], rows["area_m2"] = 9, 1, 1000
    rows[TARGET] = np.arange(11) + 100
    rows["target_unit"] = "kg_per_reported_crop_cycle"
    rows["target_candidate"] = True
    rows["pre_adoption_metadata_eligible"] = True
    rows["quality_flags"] = "[]"
    return rows


def test_unconfirmed_area_is_excluded_without_changing_recorded_outlier():
    source = candidates()
    source.loc[0, "pre_adoption_metadata_eligible"] = False
    source.loc[0, "area_m2"] = np.nan
    source.loc[1, TARGET] = 14_604_000
    source.loc[1, "quality_flags"] = json.dumps([OUTLIER_FLAG])
    rows, audit = prepare_rows(source)
    assert audit["excluded_missing_confirmed_metadata_ids"] == ["source:0"]
    assert rows.loc[rows["source_record_id"].eq("source:1"), TARGET].item() == 14_604_000
    assert rows["outlier_review"].sum() == 1


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_period", "wrong_unit", "invalid_area", "date_disagreement"])
def test_invalid_contract_is_rejected(change):
    source = candidates()
    if change == "duplicate_id":
        source.loc[1, "source_record_id"] = source.loc[0, "source_record_id"]
    elif change == "duplicate_period":
        source.loc[1, ["planting_date", "planting_year"]] = ["2020-09-01", 2020]
    elif change == "wrong_unit":
        source.loc[0, "target_unit"] = "count"
    elif change == "invalid_area":
        source.loc[0, "area_m2"] = 0
    else:
        source.loc[0, "planting_day"] = 2
    with pytest.raises(ValueError):
        prepare_rows(source)


def test_feature_allowlist_ignores_outcomes_end_dates_year_ids_and_flags():
    rows, _ = prepare_rows(candidates())
    before = features(rows)
    for name in [TARGET, "source_record_id", "farm_group", "planting_year", "actual_end_date",
                 "cycle_duration", "income", "grade_quantities", "environment", "outlier_review"]:
        rows[name] = "changed_future_information"
    pd.testing.assert_frame_equal(features(rows), before)
    assert list(before.columns) == FEATURES


def test_facility_folds_and_sensitivity_keep_original_fold_assignment():
    rows, _ = prepare_rows(candidates())
    rows["fold"] = assign_folds(rows)
    assert set(rows["fold"]) == set(range(5))
    assert rows.groupby("farm_group")["fold"].nunique().eq(1).all()
    subset = rows.iloc[1:]
    assert subset["fold"].equals(rows.loc[subset.index, "fold"])
    for fold in range(5):
        assert set(subset.loc[subset["fold"].eq(fold), "farm_group"]).isdisjoint(
            subset.loc[~subset["fold"].eq(fold), "farm_group"])


def test_baselines_only_use_training_labels_and_scale_confirmed_area():
    train = pd.DataFrame({TARGET: [100, 300, 500], "planting_month": [9, 9, 10],
                          "area_m2": [100, 100, 100]})
    query = pd.DataFrame({TARGET: [1e9, -1], "planting_month": [9, 8], "area_m2": [200, 50]})
    predicted = baselines(train, query)
    np.testing.assert_array_equal(predicted["global_median"], [300, 300])
    np.testing.assert_array_equal(predicted["month_median"], [200, 300])
    np.testing.assert_array_equal(predicted["area_scaled_median"], [600, 150])
    query[TARGET] = 0
    for name, values in predicted.items():
        np.testing.assert_array_equal(values, baselines(train, query)[name])


def test_scores_do_not_hide_the_huge_recorded_value():
    oof = pd.DataFrame({TARGET: [10, 14_604_000], "model": [10, 10], "fold": [0, 1]})
    scored = summarize_predictions(oof, ["model"])["model"]
    assert scored["n_scored"] == 2
    assert scored["mae_kg"] == (14_604_000 - 10) / 2
    oof.loc[0, "model"] = np.nan
    with pytest.raises(ValueError):
        summarize_predictions(oof, ["model"])
