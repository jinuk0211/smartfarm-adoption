"""Offline behavioral checks for target identity, source integrity and metadata joins."""

import csv
import io
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import openpyxl

from scripts import prepare_strawberry_curation as prep


def shipping(**changes):
    row = {"시설ID": "TEST_A", "작기명": "2023 딸기", "품목": "딸기", "품종": "설향",
           "정식시작일": date(2023, 9, 1), "정식종료일": date(2024, 6, 1), "총출하수량": 200,
           "최상등급수량": 0, "상등급수량": 0, "중등급수량": 0, "하등급수량": 0, "수익금액": 50000}
    row.update(changes)
    return {**row, "source_record_id": "shipping:2", "source_raw_record_json": prep.canonical(
        {key: prep.serialize(value) for key, value in row.items()})}


CYCLE = {"fcltyId": "TEST_A", "fixplntngDe": "2023-09-01", "crpsnEndDe": "2024-06-01",
         "itemCodeNm": "딸기", "itemCode": "test", "crpsnSn": "12", "fcltyYear": "2023",
         "spciesCodeNm": "설향", "ctvtAr": "100", "source_record_id": "api:cycle:1"}
CATALOG = {**CYCLE, "source_record_id": "api:catalog:1", "fcltySidoCodeNm": "테스트도",
           "fcltySigunguCodeNm": "테스트시", "fcltyTyCodeNm": "비닐", "ctvtMthdCodeNm": "수경",
           "scspnMltspnSeCodeNm": "단동"}


def normalize(rows, cycles=None, catalog=None):
    return prep.normalize_shipping(rows, [CYCLE] if cycles is None else cycles,
                                   [CATALOG] if catalog is None else catalog, date(2026, 10, 9))


def write_sources(directory):
    path = directory / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for table, filename in prep.FILENAMES.items():
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(prep.HEADERS[table])
            if table == "shipping":
                row = shipping()
                sheet.append([row[name] for name in prep.HEADERS[table]])
            payload = io.BytesIO()
            workbook.save(payload)
            archive.writestr("dataset/" + filename, payload.getvalue())
    content = path.read_bytes()
    acquisition = directory / "acquisition.json"
    acquisition.write_text(json.dumps({"file": path.name, "bytes": len(content), "acquired": True,
                                       "sha256": prep.digest(content)}), encoding="utf-8")
    return path, acquisition


class StrawberryPreparationTests(unittest.TestCase):
    def test_exact_unique_metadata_enables_only_reported_cycle_target(self):
        source = shipping()
        row = normalize([source])[0]
        self.assertTrue(row["target_candidate"])
        self.assertTrue(row["pre_adoption_metadata_eligible"])
        self.assertEqual(row["area_m2"], 100)
        self.assertEqual(row["reported_cycle_kg_per_m2"], 2)
        self.assertEqual(row["farm_group"], "TEST_A")
        self.assertFalse(row["completeness_verified"])
        self.assertEqual(row["source_raw_record_json"], source["source_raw_record_json"])

    def test_zero_and_missing_are_not_valid_zero_yield_targets(self):
        for quantity, expected in [(0, "zero_quantity_meaning_unknown"), (None, "missing_or_invalid_quantity"),
                                   (-2, "negative_quantity"), (float("inf"), "missing_or_invalid_quantity")]:
            with self.subTest(quantity=quantity):
                row = normalize([shipping(총출하수량=quantity)])[0]
                self.assertFalse(row["target_candidate"])
                self.assertIn(expected, json.loads(row["exclusion_reasons"]))
                self.assertEqual(row["총출하수량"], quantity)

    def test_duplicate_or_conflicting_periods_preserved_and_all_excluded(self):
        for second in [shipping(), shipping(총출하수량=0)]:
            with self.subTest(second=second["총출하수량"]):
                rows = normalize([shipping(), second])
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(not row["target_candidate"] for row in rows))
                self.assertTrue(all(row["same_period_row_count"] == 2 for row in rows))
                self.assertEqual([r["총출하수량"] for r in rows], [200, second["총출하수량"]])

    def test_same_cycle_name_with_conflicting_dates_is_not_split_into_independent_targets(self):
        rows = normalize([shipping(), shipping(정식종료일=date(2024, 5, 1))])
        self.assertTrue(all("same_named_cycle_conflicting_periods" in row["exclusion_reasons"] for row in rows))

    def test_all_same_facility_cycles_keep_same_group(self):
        rows = normalize([shipping(), shipping(작기명="2024 딸기", 정식시작일=date(2024, 9, 1),
                                               정식종료일=date(2025, 6, 1))])
        self.assertTrue(all(row["farm_group"] == "TEST_A" for row in rows))
        self.assertEqual(len(rows), 2)

    def test_bad_future_and_long_dates_are_excluded(self):
        for changes, reason in [({"정식종료일": date(2023, 8, 1)}, "nonpositive_cycle_duration"),
                                ({"정식종료일": date(2027, 1, 1)}, "future_or_not_yet_ended_cycle"),
                                ({"정식종료일": None}, "missing_or_invalid_cycle_date"),
                                ({"정식종료일": date(2025, 1, 1)}, "cycle_longer_than_366_days_review")]:
            with self.subTest(reason=reason):
                row = normalize([shipping(**changes)])[0]
                self.assertFalse(row["target_candidate"])
                self.assertIn(reason, json.loads(row["exclusion_reasons"]))

    def test_no_facility_only_or_nearest_date_matching(self):
        row = normalize([shipping(정식시작일=date(2023, 9, 2))])[0]
        self.assertTrue(row["target_candidate"])
        self.assertFalse(row["pre_adoption_metadata_eligible"])
        self.assertEqual(row["metadata_match_status"], "unknown_no_exact_cycle")
        self.assertNotIn("area_m2", row)

    def test_duplicate_api_cycles_are_not_arbitrarily_selected(self):
        row = normalize([shipping()], cycles=[CYCLE, {**CYCLE, "crpsnSn": "13"}])[0]
        self.assertFalse(row["pre_adoption_metadata_eligible"])
        self.assertEqual(row["metadata_match_status"], "conflict_multiple_exact_cycles")

    def test_duplicate_catalog_and_conflicting_metadata_never_populate_area(self):
        cases = [([CATALOG, CATALOG], "conflict_or_missing_catalog"),
                 ([{**CATALOG, "ctvtAr": "200"}], "conflict_area_metadata"),
                 ([{**CATALOG, "spciesCodeNm": "다른품종"}], "conflict_variety_metadata"),
                 ([{**CATALOG, "itemCodeNm": "오이"}], "conflict_crop_metadata")]
        for catalogs, status in cases:
            with self.subTest(status=status):
                row = normalize([shipping()], catalog=catalogs)[0]
                self.assertEqual(row["metadata_match_status"], status)
                self.assertNotIn("area_m2", row)

    def test_million_kg_value_is_flagged_not_corrected_deleted_or_included_as_feature(self):
        row = normalize([shipping(총출하수량=14_604_000)])[0]
        self.assertEqual(row["reported_cycle_total_kg"], 14_604_000)
        self.assertTrue(row["target_candidate"])
        self.assertIn("million_kg", row["quality_flags"])
        self.assertTrue(set(prep.FEATURE_COLUMNS).isdisjoint({"quality_flags", "farm_group", "reported_cycle_total_kg",
                                                            "cycle_duration_days_audit_only", "수익금액", "정식종료일"}))

    def test_zip_integrity_and_row_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, acquisition = write_sources(Path(temporary))
            tables, evidence = prep.read_source(path, acquisition)
            row = tables["shipping"][0]
            self.assertEqual(row["source_excel_row"], 2)
            self.assertEqual(row["총출하수량"], 200)
            self.assertEqual(row["source_zip_sha256"], evidence["zip_sha256"])
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(prep.PreparationError, "mismatch"):
                prep.read_source(path, acquisition)

    def test_invalid_workbook_is_closed_when_schema_validation_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, acquisition = write_sources(Path(temporary))
            workbook = Mock(worksheets=[])
            with patch.object(prep.openpyxl, "load_workbook", return_value=workbook):
                with self.assertRaisesRegex(prep.PreparationError, "sheet count"):
                    prep.read_source(path, acquisition)
            workbook.close.assert_called_once_with()

    def test_api_metadata_hash_checked_before_matching(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            audit = {"source_run_id": "fixture", "output_files": {}}
            for table, row in [("cycles", CYCLE), ("catalog", CATALOG)]:
                filename = f"smartfarm_api_{table}.csv"
                with (directory / filename).open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
                content = (directory / filename).read_bytes()
                audit["output_files"][filename] = {"sha256": prep.digest(content), "bytes": len(content)}
            (directory / "smartfarm_api_audit.json").write_text(json.dumps(audit), encoding="utf-8")
            cycles, _, _ = prep.read_api_metadata(directory)
            self.assertEqual(cycles[0]["fcltyId"], "TEST_A")
            (directory / "smartfarm_api_cycles.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(prep.PreparationError, "hash mismatch"):
                prep.read_api_metadata(directory)


if __name__ == "__main__":
    unittest.main()
