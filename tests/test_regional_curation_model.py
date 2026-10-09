"""Behavioral checks for held-out labels, facility isolation and input leakage."""

import unittest

import numpy as np
import pandas as pd

from src import regional_curation_model as model


def rows():
    return pd.DataFrame([
        {"source_row_id": f"row{index:03}", "cycle_id": f"cycle{index}",
         "facility_id": f"farm{index // 2}", "crop": "딸기" if index % 3 else "토마토",
         "cultivar": "설향" if index % 3 else None, "province": "경상남도",
         "district": "진주시" if index % 2 else "김해시", "facility_type": "비닐",
         "planting_year": 2020 + index % 2, "planting_month": 8 + index % 2,
         model.TARGET: (index + 1) * 100_000, "large_revenue_review_flag": False}
        for index in range(20)])


class RegionalModelTests(unittest.TestCase):
    def test_repeated_facilities_never_cross_folds_and_sensitivity_keeps_assignments(self):
        data, _ = model.prepare_rows(rows())
        data.loc[0, model.TARGET] = 233_563_333_310
        data.loc[0, "large_revenue_review_flag"] = True
        data["fold"] = model.assign_folds(data)
        self.assertTrue(data.groupby("facility_id")["fold"].nunique().eq(1).all())
        self.assertEqual(set(data["fold"]), set(range(5)))
        sensitivity = data.loc[~data["large_revenue_review_flag"]].copy()
        pd.testing.assert_series_equal(sensitivity["fold"], data.loc[sensitivity.index, "fold"])
        for number in range(5):
            train, query = data.loc[data["fold"].ne(number)], data.loc[data["fold"].eq(number)]
            self.assertFalse(set(train["facility_id"]) & set(query["facility_id"]))

    def test_target_and_future_outcome_changes_do_not_change_classical_predictions(self):
        data, _ = model.prepare_rows(rows())
        train, query = data.iloc[:16], data.iloc[16:].copy()
        before = model.classical_predictions(train, query)
        query[model.TARGET] = 999_999_999_999
        query["actual_end_date"] = "2999-01-01"
        query["shipment_count_source_definition"] = 1e20
        query["area_source_definition_pyeong"] = 1e20
        query["api_area_m2_verified_metadata"] = 1e20
        query["large_revenue_review_flag"] = True
        after = model.classical_predictions(train, query)
        for name in model.CLASSICAL:
            with self.subTest(model=name):
                np.testing.assert_allclose(before[name], after[name], rtol=0, atol=0)

    def test_unseen_crop_baseline_uses_training_global_median(self):
        data = rows()
        query = data.iloc[:1].copy()
        query["crop"] = "unseen crop"
        query[model.TARGET] = 1e30
        for values in model.baselines(data, query).values():
            self.assertEqual(values[0], data[model.TARGET].median())

    def test_missing_groups_duplicate_ids_and_unusable_targets_rejected(self):
        for column, value in [("facility_id", None), (model.TARGET, 0), (model.TARGET, float("nan"))]:
            data = rows()
            data.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                model.prepare_rows(data)
        data = rows()
        data.loc[1, "cycle_id"] = data.loc[0, "cycle_id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            model.prepare_rows(data)

    def test_extreme_source_target_retained_and_incomplete_oof_rejected(self):
        data = rows()
        data.loc[0, model.TARGET] = 233_563_333_310
        data.loc[0, "large_revenue_review_flag"] = True
        prepared, audit = model.prepare_rows(data)
        self.assertEqual(len(prepared), len(data))
        self.assertEqual(audit["target_max_krw"], 233_563_333_310)
        prepared["fold"] = model.assign_folds(prepared)
        prepared["test_model"] = np.nan
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            model.summarize_predictions(prepared, ["test_model"])


if __name__ == "__main__":
    unittest.main()
