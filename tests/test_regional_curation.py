"""Behavioral data-contract tests on explicit synthetic source records."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts import prepare_regional_curation as prep


def source(**changes):
    row = dict(zip(prep.HEADERS, ["F1", "2020 strawberry", datetime(2020, 9, 1),
        datetime(2021, 5, 31), "딸기", "설향", 100, 1000, "비닐", "경상남도", "진주시",
        500, 0, 500, 0, 0, 1_000_000], strict=True))
    row.update(changes)
    return row


class RegionalPreparationTests(unittest.TestCase):
    def test_missing_zero_and_negative_sales_are_distinct_not_imputed(self):
        for value, status in [(None, "missing"), (0, "zero"), (-1, "negative")]:
            with self.subTest(value=value):
                row = prep.normalize([source(수입금액=value)])[0]
                self.assertFalse(row["eligible_recorded_sales"])
                self.assertEqual(row["revenue_status"], status)
                self.assertEqual(row[prep.TARGET], value)

    def test_exact_duplicate_preserves_original_row_mapping(self):
        rows = prep.normalize([source(), source()])
        self.assertEqual([row["eligible_recorded_sales"] for row in rows], [True, False])
        self.assertEqual(json.loads(rows[0]["exact_duplicate_source_rows_json"]), [2, 3])
        self.assertEqual(json.loads(rows[0]["source_raw_record_json"])["증등급출하량"], 0)

    def test_conflicting_missing_and_positive_same_cycle_both_excluded(self):
        rows = prep.normalize([source(), source(수입금액=None, 작기명="other label")])
        self.assertTrue(all(row["ambiguous_cycle"] for row in rows))
        self.assertTrue(all(not row["eligible_recorded_sales"] for row in rows))
        self.assertEqual(rows[0][prep.TARGET], 1_000_000)

    def test_changed_end_date_does_not_hide_ambiguous_cycle(self):
        rows = prep.normalize([source(), source(작기종료일자=datetime(2021, 6, 30))])
        self.assertTrue(all(row["ambiguous_cycle"] for row in rows))

    def test_bad_cycle_dates_excluded(self):
        for end in [None, "0001-01-01", datetime(2019, 1, 1)]:
            self.assertFalse(prep.normalize([source(작기종료일자=end)])[0]["eligible_recorded_sales"])

    def test_definition_api_area_conflict_not_silently_converted(self):
        matches = {("F1", "2020-09-01", "2021-05-31", "딸기"):
                   [{"area_m2": 100, "cycle_id": "C1", "catalog_id": "A1"}]}
        row = prep.normalize([source()], matches)[0]
        self.assertEqual(row["api_area_comparison"], "raw_number_equals_api_m2_definition_conflict")
        self.assertEqual(row["api_area_m2_verified_metadata"], 100)
        self.assertAlmostEqual(row["area_m2_if_definition_correct_audit_only"], 100 * 400 / 121)
        self.assertFalse(any("area" in name for name in prep.FEATURES))

    def test_ambiguous_api_join_does_not_supply_area(self):
        match = {"area_m2": 100, "cycle_id": "C1", "catalog_id": "A1"}
        rows = prep.normalize([source()], {("F1", "2020-09-01", "2021-05-31", "딸기"): [match, match]})
        self.assertIsNone(rows[0]["api_area_m2_verified_metadata"])
        self.assertEqual(rows[0]["api_area_comparison"], "ambiguous_cycle_match")

    def test_large_revenue_preserved_and_future_fields_excluded(self):
        row = prep.normalize([source(수입금액=233_563_333_310)])[0]
        self.assertTrue(row["eligible_recorded_sales"])
        self.assertTrue(row["large_revenue_review_flag"])
        self.assertEqual(row[prep.TARGET], 233_563_333_310)
        self.assertEqual(prep.FEATURES, ["crop", "cultivar", "province", "district", "facility_type",
                                      "planting_year", "planting_month"])

    def test_changed_download_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.xlsx"
            path.write_bytes(b"changed")
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(json.dumps({"sha256": prep.SOURCE_SHA256, "acquired": True,
                                            "bytes": path.stat().st_size}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                prep.verified_xlsx(path, manifest)


if __name__ == "__main__":
    unittest.main()
