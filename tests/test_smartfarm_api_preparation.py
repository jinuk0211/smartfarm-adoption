"""Offline integrity/join tests; actual pilot is read only and never used for learning."""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_smartfarm_api as prep


CATALOG = {"fcltyId": "TEST_FARM", "crpsnSn": 12, "fcltyYear": "2024",
           "itemCode": "TEST_CROP", "itemCodeNm": "딸기", "ctvtAr": 100,
           "statusCode": "00", "statusMessage": "NORMAL_CODE"}
CYCLE = {**CATALOG, "fixplntngDe": "2024-01-01", "crpsnEndDe": "2024-12-31"}
OUTPUT = {"fcltyId": "TEST_FARM", "crpsnSn": 12, "opShipDe": "2024-06-01",
          "opAllShip": 0, "opIncome": 0, "opNote": "", "statusCode": "00", "statusMessage": "NORMAL_CODE"}
# Observed 20261009T085610Z_58b5fc39 no-data schema, not a real zero-cost observation.
NO_DATA_COST = {"fcltyId": None, "crpsnSn": 0, "ctPayDe": None, "ctOpcWkCost": 0,
                "ctFmwWkTime": 0, "fmwWkCost": 0, "ctFmwWkPpl": 0,
                "statusCode": "03", "statusMessage": "NODATA_ERROR"}
PARAMS = {"fcltyId": "TEST_FARM", "crpsnSn": 12, "fixPlntngDe": "20240101", "crpsnEndDe": "20241231"}


def write_run(root, catalog=None, cycles=None, output=None, cost=None, status="completed", params=None):
    """Create explicitly specified artificial responses and matching integrity evidence."""
    run = Path(root) / "run"
    run.mkdir()
    operations = [
        ("getFcltyInfoDataList", {}, [CATALOG] if catalog is None else catalog),
        ("getFcltyDateInfoData", {"fcltyId": "TEST_FARM", "fcltyYear": "2024"}, [CYCLE] if cycles is None else cycles),
        ("getMngtOutputDataList", PARAMS if params is None else params, [OUTPUT] if output is None else output),
        ("getMngtCostDataList", PARAMS if params is None else params, [NO_DATA_COST] if cost is None else cost),
    ]
    manifest = {"endpoint_base": prep.BASE_URL, "status": status, "requests": [],
                "selection": {}, "coverage": {"unvisited_facility_year_count": 0, "limit_reasons": []},
                "skipped_cycles": [], "completed_at_utc": "2026-10-09T00:00:00Z" if status == "completed" else None}
    for index, (operation, request_params, payload) in enumerate(operations, 1):
        no_data = bool(payload and payload[0].get("statusCode") == "03")
        rows = [] if no_data else payload
        response_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        records_bytes = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
        response_name, records_name = f"{index}.response.json", f"{index}.records.jsonl"
        (run / response_name).write_bytes(response_bytes)
        (run / records_name).write_bytes(records_bytes)
        manifest["requests"].append({
            "source_operation": operation, "parameters": request_params, "status": "saved", "no_data": no_data,
            "record_count": len(rows), "response_file": response_name, "records_file": records_name,
            "response_sha256": prep.sha256(response_bytes), "records_sha256": prep.sha256(records_bytes),
            "retrieved_at_utc": "2026-10-09T00:00:00Z",
        })
    path = run / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def load_audit(path):
    manifest, _, tables, requests = prep.load_run(path)
    return prep.audit_tables(manifest, tables, requests), tables, requests


class PreparationTests(unittest.TestCase):
    def test_actual_completed_pilot_to_temporary_output_preserves_fields_and_missing_cost(self):
        path = prep.ROOT / "data/raw/smartfarm_api/20261009T085610Z_58b5fc39/manifest.json"
        if not path.exists():
            self.skipTest("Local authenticated pilot fixture is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            audit = prep.prepare(path, Path(temporary))
            self.assertEqual(audit["row_counts"], {"catalog": 651, "cycles": 1, "output": 1, "cost": 0})
            self.assertTrue(audit["request_scope_complete"])
            self.assertFalse(audit["training_eligible"])
            self.assertEqual(audit["no_data_requests_by_operation"], {"getMngtCostDataList": 1})
            self.assertEqual(audit["source_manifest_sha256"], prep.sha256(path.read_bytes()))
            self.assertEqual((Path(temporary) / audit["source_manifest_snapshot"]).read_bytes(), path.read_bytes())
            with (Path(temporary) / "smartfarm_api_output.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["opAllShip"], "24000")
            self.assertEqual(json.loads(rows[0]["source_raw_record_json"])["opIncome"], 300000000)
            self.assertEqual(rows[0]["audit_cycle_join_status"], "matched")

    def test_no_data_cost_is_missing_and_normal_zero_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit, tables, _ = load_audit(write_run(temporary))
            self.assertTrue(audit["request_scope_complete"])
            self.assertEqual(tables["cost"], [])
            self.assertEqual(tables["output"][0]["opAllShip"], 0)
            self.assertEqual(tables["cycles"][0]["audit_cost_request_status"], "no_data")
            self.assertEqual(tables["cycles"][0]["audit_output_request_status"], "records")

    def test_corrupted_response_or_records_hash_creates_no_output(self):
        for name in ("1.response.json", "3.records.jsonl"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = write_run(temporary)
                (path.parent / name).write_bytes(b"[]")
                destination = Path(temporary) / "normalized"
                with self.assertRaises(prep.PreparationError):
                    prep.prepare(path, destination)
                self.assertFalse(destination.exists())

    def test_row_count_and_no_data_metadata_are_verified(self):
        for index, field, value in [(2, "record_count", 99), (3, "no_data", False)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = write_run(temporary)
                manifest = json.loads(path.read_bytes())
                manifest["requests"][index][field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(prep.PreparationError):
                    prep.load_run(path)

    def test_valid_hash_does_not_hide_response_record_disagreement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary)
            manifest = json.loads(path.read_bytes())
            content = (json.dumps({**OUTPUT, "opAllShip": 999}) + "\n").encode()
            (path.parent / "3.records.jsonl").write_bytes(content)
            manifest["requests"][2]["records_sha256"] = prep.sha256(content)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(prep.PreparationError):
                prep.load_run(path)

    def test_facility_cycle_with_two_years_is_ambiguous_without_row_multiplication(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary, cycles=[CYCLE, {**CYCLE, "fcltyYear": "2025"}])
            _, tables, _ = load_audit(path)
            self.assertEqual(len(tables["output"]), 1)
            self.assertEqual(tables["output"][0]["audit_cycle_join_status"], "ambiguous")
            self.assertNotIn("audit_cycle_area_m2", tables["output"][0])
            self.assertIn("request_identity_mismatch", tables["cycles"][1]["audit_flags"])

    def test_catalog_crop_conflict_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, tables, _ = load_audit(write_run(temporary, catalog=[{**CATALOG, "itemCodeNm": "오이"}]))
            self.assertIn("crop_mismatch", tables["cycles"][0]["audit_flags"])

    def test_request_cycle_date_and_identity_mismatches_are_separate(self):
        rows = [OUTPUT, {**OUTPUT, "opShipDe": "2025-01-01"}, {**OUTPUT, "fcltyId": "OTHER"}]
        with tempfile.TemporaryDirectory() as temporary:
            params = {**PARAMS, "fixPlntngDe": "20240701"}
            _, tables, _ = load_audit(write_run(temporary, output=rows, params=params))
            self.assertIn("outside_request_period", tables["output"][0]["audit_flags"])
            self.assertNotIn("outside_cycle_period", tables["output"][0]["audit_flags"])
            self.assertIn("outside_cycle_period", tables["output"][1]["audit_flags"])
            self.assertIn("request_identity_mismatch", tables["output"][2]["audit_flags"])
            self.assertEqual(tables["output"][2]["audit_cycle_join_status"], "missing")

    def test_duplicates_and_multiple_same_day_rows_are_kept_not_aggregated(self):
        rows = [OUTPUT, OUTPUT, {**OUTPUT, "opAllShip": 7}]
        with tempfile.TemporaryDirectory() as temporary:
            audit, tables, _ = load_audit(write_run(temporary, output=rows))
            self.assertEqual(len(tables["output"]), 3)
            self.assertEqual([row["opAllShip"] for row in tables["output"]], [0, 0, 7])
            self.assertEqual([row["audit_exact_duplicate_count"] for row in tables["output"]], [2, 2, 1])
            self.assertEqual([row["audit_same_day_record_count"] for row in tables["output"]], [3, 3, 3])
            self.assertEqual(audit["quantity_revenue_cost_aggregation"], "not_performed")

    def test_missing_zero_and_invalid_area_are_not_imputed(self):
        for area, expected in [(None, "missing"), (0, "zero"), (-1, "invalid"), ("unknown", "invalid")]:
            with self.subTest(area=area), tempfile.TemporaryDirectory() as temporary:
                _, tables, _ = load_audit(write_run(temporary, cycles=[{**CYCLE, "ctvtAr": area}]))
                self.assertEqual(tables["cycles"][0]["ctvtAr"], area)
                self.assertEqual(tables["output"][0]["audit_area_status"], expected)

    def test_running_zero_unvisited_counter_is_not_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit, _, _ = load_audit(write_run(temporary, status="in_progress"))
            self.assertEqual(audit["source_coverage"]["unvisited_facility_year_count"], 0)
            self.assertFalse(audit["request_scope_complete"])
            self.assertFalse(audit["training_eligible"])

    def test_completed_label_does_not_hide_unvisited_catalog_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary, catalog=[CATALOG, {**CATALOG, "fcltyId": "SECOND"}])
            audit, _, _ = load_audit(path)
            self.assertEqual(audit["missing_facility_year_count"], 1)
            self.assertFalse(audit["request_scope_complete"])

    def test_missing_cost_request_is_not_no_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary)
            manifest = json.loads(path.read_bytes())
            manifest["requests"].pop()
            path.write_text(json.dumps(manifest), encoding="utf-8")
            audit, tables, _ = load_audit(path)
            self.assertEqual(tables["cycles"][0]["audit_cost_request_status"], "not_requested")
            self.assertEqual(audit["no_data_requests_by_operation"], {})
            self.assertEqual(audit["missing_management_request_count"], 1)
            self.assertFalse(audit["request_scope_complete"])

    def test_cycle_lookup_can_complete_without_returning_all_catalog_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary, catalog=[CATALOG, {**CATALOG, "crpsnSn": 13}])
            audit, _, _ = load_audit(path)
            self.assertTrue(audit["request_scope_complete"])
            self.assertEqual(audit["missing_catalog_cycle_count"], 1)
            self.assertFalse(audit["catalog_cycle_coverage_complete"])
            self.assertFalse(audit["training_eligible"])

    def test_notes_count_keywords_without_claiming_period_definition(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit, tables, _ = load_audit(write_run(temporary, output=[{**OUTPUT, "opNote": "작기 전체 누적"}]))
            self.assertEqual(audit["output_note_audit"]["nonempty_rows"], 1)
            self.assertEqual(audit["output_note_audit"]["period_keyword_row_counts"], {"작기": 1, "전체": 1, "누적": 1})
            self.assertFalse(tables["output"][0]["audit_training_eligible"])

    def test_manifest_mid_write_or_unsafe_source_path_stops_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_run(temporary)
            manifest = json.loads(path.read_bytes())
            manifest["requests"][0]["response_file"] = "../outside.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(prep.PreparationError):
                prep.load_run(path)
            path.write_text('{"status":', encoding="utf-8")
            output = Path(temporary) / "out"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(prep.main(["--manifest", str(path), "--output-dir", str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
