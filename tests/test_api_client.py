"""Offline tests: artificial rows and observed no-data sentinels, never training data."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import quote


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/collect_smartfarm_api.py"
SPEC = importlib.util.spec_from_file_location("smartfarm_api_client", MODULE_PATH)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)

# Copied from the two approved-key pilot responses, not production observations.
NO_DATA_OUTPUT = [{
    "fcltyId": None, "crpsnSn": 0, "opShipDe": None, "opAllShip": 0,
    "opLvAa": 0, "opLvA": 0, "opLvB": 0, "opLvC": 0,
    "opLvAaWon": 0, "opLvAWon": 0, "opLvBWon": 0, "opLvCWon": 0,
    "opIncome": 0, "opUnpsRate": 0, "opShipPlc": None, "opNote": None,
    "statusCode": "03", "statusMessage": "NODATA_ERROR",
}]
NO_DATA_COST = [{
    "fcltyId": None, "crpsnSn": 0, "ctPayDe": None, "ctOpcWkCost": 0,
    "ctFmwWkTime": 0, "fmwWkCost": 0, "ctFmwWkPpl": 0,
    "statusCode": "03", "statusMessage": "NODATA_ERROR",
}]
MANAGEMENT_PARAMS = {"fcltyId": "TEST_FARM", "crpsnSn": 12,
                     "fixPlntngDe": "20240101", "crpsnEndDe": "20241231"}


class MockResponse(io.BytesIO):
    status = 200


class MockOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        body = result if isinstance(result, bytes) else json.dumps(result).encode("utf-8")
        return MockResponse(body)


class APIClientTests(unittest.TestCase):
    key = "TEST_ONLY_SECRET+/="
    row = {"fcltyId": "TEST_FARM", "crpsnSn": 12, "opAllShip": 10}

    def setUp(self):
        self.sleep_patch = patch.object(api.time, "sleep")
        self.sleep = self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    @staticmethod
    def args(**overrides):
        values = dict(facility=None, year=None, crop=None, list_only=False, max_farms=3,
                      max_cycles=3, start=None, end=None, include_timeseries=False)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_documented_array_and_nested_wrappers(self):
        shapes = [
            [self.row], self.row, {"data": [self.row]}, {"rows": [self.row]},
            {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [self.row]}}}},
            {"result": {"records": [self.row]}},
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                api.validate_statuses(shape)
                self.assertEqual(api.extract_records(shape), [self.row])
        for shape in [[], {"data": []}, {"response": {"body": {"items": None}}},
                      [{"statusCode": "00", "statusMessage": "NORMAL_CODE"}]]:
            self.assertEqual(api.extract_records(shape), [])

    def test_failed_header_and_ambiguous_arrays_are_rejected(self):
        with self.assertRaises(api.CollectionError):
            api.validate_statuses({"response": {"header": {"resultCode": "99"}, "body": {"items": [self.row]}}})
        with self.assertRaises(api.CollectionError):
            api.extract_records({"data": [self.row], "rows": [self.row]})
        with self.assertRaises(api.CollectionError):
            api.extract_records(["not a record"])

    def test_observed_no_data_saves_evidence_but_no_business_rows(self):
        for operation, payload in [("getMngtOutputDataList", NO_DATA_OUTPUT),
                                   ("getMngtCostDataList", NO_DATA_COST)]:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                run_dir = Path(temporary) / "run"
                client = api.APIClient(self.key, run_dir, opener=MockOpener([payload]))
                self.assertEqual(client.fetch(operation, **MANAGEMENT_PARAMS), [])
                entry = client.manifest["requests"][0]
                self.assertEqual(entry["status"], "saved")
                self.assertEqual(entry["record_count"], 0)
                self.assertTrue(entry["no_data"])
                self.assertEqual(entry["api_status_code"], "03")
                self.assertEqual(entry["api_status_message"], "NODATA_ERROR")
                self.assertEqual((run_dir / entry["records_file"]).read_bytes(), b"")
                self.assertEqual(entry["records_sha256"], api.hashlib.sha256(b"").hexdigest())
                saved_response = (run_dir / entry["response_file"]).read_bytes()
                self.assertEqual(json.loads(saved_response), payload)
                self.assertEqual(entry["response_sha256"], api.hashlib.sha256(saved_response).hexdigest())

    def test_no_data_does_not_swallow_mixed_or_populated_error_rows(self):
        cases = [NO_DATA_OUTPUT + [self.row], [self.row] + NO_DATA_OUTPUT, NO_DATA_OUTPUT * 2,
                 {"data": NO_DATA_OUTPUT}]
        for field, value in [("fcltyId", "TEST_FARM"), ("crpsnSn", 12),
                             ("opAllShip", 1), ("opShipDe", "2024-01-01"),
                             ("opNote", "record exists"), ("opAllShip", False),
                             ("statusCode", "22"), ("unexpected", 0)]:
            cases.append([{**NO_DATA_OUTPUT[0], field: value}])
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                client = api.APIClient(self.key, Path(temporary) / "run", opener=MockOpener([payload]))
                with self.assertRaises(api.CollectionError):
                    client.fetch("getMngtOutputDataList", **MANAGEMENT_PARAMS)
                entry = client.manifest["requests"][0]
                self.assertEqual(entry["status"], "failed")
                self.assertTrue((client.run_dir / entry["response_file"]).exists())
                self.assertEqual(list(client.run_dir.glob("*.records.jsonl")), [])
        for operation, payload in [("getMngtCostDataList", NO_DATA_OUTPUT),
                                   ("getMngtOutputDataList", NO_DATA_COST),
                                   ("getMngtCostDataList", [{**NO_DATA_COST[0], "ctOpcWkCost": 1}])]:
            with self.subTest(operation=operation, payload=payload), self.assertRaises(api.CollectionError):
                api.response_records(payload, operation)

    def test_successful_zero_quantity_with_valid_identity_is_preserved(self):
        row = {**NO_DATA_OUTPUT[0], "fcltyId": "TEST_FARM", "crpsnSn": 12,
               "opShipDe": "2024-01-01", "statusCode": "00", "statusMessage": "NORMAL_CODE"}
        with tempfile.TemporaryDirectory() as temporary:
            client = api.APIClient(self.key, Path(temporary) / "run", opener=MockOpener([[row]]))
            self.assertEqual(client.fetch("getMngtOutputDataList", **MANAGEMENT_PARAMS), [row])
            entry = client.manifest["requests"][0]
            self.assertFalse(entry["no_data"])
            self.assertEqual(entry["record_count"], 1)
            self.assertEqual(json.loads((client.run_dir / entry["records_file"]).read_text()), row)

    def test_collector_continues_after_no_data_to_cost_and_next_cycle(self):
        farm = {"fcltyId": "TEST_FARM", "fcltyYear": "2024"}
        cycle = {**farm, "crpsnSn": 12, "fixplntngDe": "2024-01-01", "crpsnEndDe": "2024-12-31"}
        second_row = {**self.row, "crpsnSn": 13}
        opener = MockOpener([[farm], [cycle, {**cycle, "crpsnSn": 13}],
                             NO_DATA_OUTPUT, NO_DATA_COST, [second_row], []])
        with tempfile.TemporaryDirectory() as temporary:
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            api.collect(client, self.args())
            self.assertEqual(client.manifest["status"], "completed")
            self.assertEqual(client.manifest["collected_cycle_count"], 2)
            self.assertEqual(len(opener.urls), 6)
            entries = client.manifest["requests"]
            self.assertEqual([entry["record_count"] for entry in entries[2:]], [0, 0, 1, 0])
            self.assertEqual([entry["no_data"] for entry in entries[2:]], [True, True, False, False])
            self.assertEqual(json.loads((client.run_dir / entries[4]["records_file"]).read_text()), second_row)

    def test_no_data_cache_resume_preserves_empty_meaning_without_network(self):
        for operation, payload in [("getMngtOutputDataList", NO_DATA_OUTPUT),
                                   ("getMngtCostDataList", NO_DATA_COST)]:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original = api.APIClient(self.key, root / "first", opener=MockOpener([payload]))
                original.fetch(operation, **MANAGEMENT_PARAMS)
                opener = MockOpener([])
                resumed = api.APIClient(self.key, root / "second", opener=opener, resume_from=root / "first")
                self.assertEqual(resumed.fetch(operation, **MANAGEMENT_PARAMS), [])
                self.assertEqual(opener.urls, [])
                self.assertEqual(resumed.network_requests, 0)
                entry = resumed.manifest["requests"][0]
                self.assertTrue(entry["no_data"])
                self.assertEqual(entry["record_count"], 0)
                self.assertEqual(entry["transport"], "verified_cache")
                self.assertEqual(entry["original_retrieved_at_utc"], original.manifest["requests"][0]["retrieved_at_utc"])
                self.assertEqual(entry["records_sha256"], api.hashlib.sha256(b"").hexdigest())

    def test_secret_redacted_in_response_and_manifest_with_integrity_metadata(self):
        echoed = {**self.row, "note": self.key, "url": "https://example.invalid/" + quote(self.key, safe="")}
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            opener = MockOpener([[echoed]])
            client = api.APIClient(self.key, run_dir, opener=opener)
            rows = client.fetch("getFcltyInfoDataList")
            self.assertEqual(rows[0]["note"], "[REDACTED]")
            self.assertTrue(opener.urls[0].startswith("https://"))
            self.assertIn(quote(self.key, safe=""), opener.urls[0])
            entry = client.manifest["requests"][0]
            self.assertEqual(entry["record_count"], 1)
            self.assertEqual(entry["source_operation"], "getFcltyInfoDataList")
            for path in run_dir.iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(self.key, text)
                self.assertNotIn(quote(self.key, safe=""), text)
            self.assertEqual(entry["response_sha256"], api.hashlib.sha256((run_dir / entry["response_file"]).read_bytes()).hexdigest())

    def test_transport_error_does_not_echo_url_or_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            client = api.APIClient(self.key, run_dir, opener=MockOpener([URLError("https://host/" + self.key)]))
            with self.assertRaises(api.CollectionError) as error:
                client.fetch("getFcltyInfoDataList")
            self.assertNotIn(self.key, str(error.exception))
            self.assertNotIn(self.key, (run_dir / "manifest.json").read_text())
            self.assertEqual(client.manifest["requests"][0]["status"], "failed")

    def test_response_and_request_limits_fail_without_record_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = api.APIClient(self.key, Path(temporary) / "run", max_requests=1,
                                   max_response_bytes=8, opener=MockOpener([[self.row]]))
            with self.assertRaises(api.CollectionError):
                client.fetch("getFcltyInfoDataList")
            self.assertEqual(list(client.run_dir.glob("*.records.jsonl")), [])
            with self.assertRaises(api.CollectionError):
                client.fetch("getFcltyInfoDataList")
            self.assertEqual(len(client.opener.urls), 1)

    def test_redirect_is_rejected_before_followup(self):
        with self.assertRaises(api.CollectionError):
            api.RejectRedirects().redirect_request(None, None, 302, "", {}, "http://example.invalid/secret")

    def test_collector_deduplicates_facility_year_and_bounds_timeseries(self):
        farm = {"fcltyId": "TEST_FARM", "fcltyYear": "2024", "crpsnSn": 12}
        cycle = {**farm, "fixplntngDe": "2024-01-01", "crpsnEndDe": "2024-12-31", "itemCode": "TEST_CROP"}
        opener = MockOpener([[farm, farm], [cycle, cycle], [self.row], [], [], []])
        args = self.args(year=["2024"], max_farms=1, max_cycles=1,
                                  start=date(2024, 3, 1), end=date(2024, 3, 2), include_timeseries=True)
        with tempfile.TemporaryDirectory() as temporary:
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            api.collect(client, args)
            self.assertEqual(len(opener.urls), 6)
            self.assertTrue(all(url.endswith("/20240301/20240302") for url in opener.urls[2:]))
            self.assertIn("/getEnvInfoDataList/", opener.urls[4])
            self.assertEqual(client.manifest["collected_cycle_count"], 1)
            self.assertEqual(client.manifest["shipment_aggregation"], "not_performed_cumulative_definition_unverified")
            self.assertFalse(client.manifest["training_eligible"])

    def test_invalid_cycle_dates_are_skipped(self):
        farm = {"fcltyId": "TEST_FARM", "fcltyYear": "2024"}
        bad = {**farm, "crpsnSn": 1, "fixplntngDe": "", "crpsnEndDe": "2024-12-31"}
        with tempfile.TemporaryDirectory() as temporary:
            opener = MockOpener([[farm], [bad]])
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            args = self.args(max_farms=1, max_cycles=1,
                                      start=None, end=None, include_timeseries=False)
            api.collect(client, args)
            self.assertEqual(len(opener.urls), 2)
            self.assertEqual(client.manifest["skipped_cycles"][0]["reason"], "invalid_identity_or_crop_dates")
            self.assertEqual(client.manifest["status"], "completed_with_skips")

    def test_list_only_never_requests_cycles_or_management(self):
        farms = [{"fcltyId": "F1", "fcltyYear": "2024", "itemCodeNm": "딸기"},
                 {"fcltyId": "F1", "fcltyYear": "2023", "itemCodeNm": "딸기"}]
        with tempfile.TemporaryDirectory() as temporary:
            opener = MockOpener([farms])
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            api.collect(client, self.args(list_only=True))
            self.assertEqual(len(opener.urls), 1)
            self.assertEqual(client.manifest["catalog"]["facility_count"], 1)
            self.assertEqual(client.manifest["catalog"]["facility_year_count"], 2)
            self.assertEqual(client.manifest["status"], "catalog_only")

    def test_crop_filter_applies_to_catalog_and_cycle_records(self):
        farm = {"fcltyId": "F1", "fcltyYear": "2024", "itemCodeNm": "딸기"}
        ignored_farm = {**farm, "fcltyId": "F2", "itemCodeNm": "국화"}
        cycle = {**farm, "crpsnSn": 1, "fixplntngDe": "2024-01-01", "crpsnEndDe": "2024-12-31"}
        ignored_cycle = {**cycle, "crpsnSn": 2, "itemCodeNm": "국화"}
        with tempfile.TemporaryDirectory() as temporary:
            opener = MockOpener([[farm, ignored_farm], [cycle, ignored_cycle], [], []])
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            api.collect(client, self.args(crop=["딸기"]))
            self.assertEqual(len(opener.urls), 4)
            self.assertEqual(client.manifest["collected_cycle_count"], 1)
            self.assertEqual(client.manifest["status"], "completed")

    def test_facility_and_cycle_limits_mark_truncation(self):
        farm = {"fcltyId": "F1", "fcltyYear": "2024"}
        cycle = {**farm, "crpsnSn": 1, "fixplntngDe": "2024-01-01", "crpsnEndDe": "2024-12-31"}
        farms = [farm, {**farm, "fcltyYear": "2023"}, {**farm, "fcltyId": "F2"}]
        with tempfile.TemporaryDirectory() as temporary:
            opener = MockOpener([farms, [cycle, {**cycle, "crpsnSn": 2}], [], []])
            client = api.APIClient(self.key, Path(temporary) / "run", opener=opener)
            api.collect(client, self.args(max_farms=1, max_cycles=1))
            self.assertEqual(client.manifest["status"], "truncated")
            coverage = client.manifest["coverage"]
            self.assertEqual(coverage["facilities_omitted_by_limit"], 1)
            self.assertEqual(coverage["cycles_omitted_by_limit"], 1)
            self.assertEqual(coverage["unvisited_facility_year_count"], 1)
            self.assertEqual(coverage["limit_reasons"], ["max_farms", "max_cycles"])

    def test_verified_resume_reuses_response_and_preserves_original_timestamp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = api.APIClient(self.key, root / "first", opener=MockOpener([[self.row]]))
            original.fetch("getFcltyInfoDataList")
            opener = MockOpener([])
            resumed = api.APIClient(self.key, root / "second", opener=opener, resume_from=root / "first")
            self.assertEqual(resumed.fetch("getFcltyInfoDataList"), [self.row])
            self.assertEqual(opener.urls, [])
            self.assertEqual(resumed.network_requests, 0)
            self.assertEqual(resumed.manifest["reused_response_count"], 1)
            entry = resumed.manifest["requests"][0]
            self.assertEqual(entry["original_retrieved_at_utc"], original.manifest["requests"][0]["retrieved_at_utc"])
            self.assertNotIn(self.key, (root / "second/manifest.json").read_text())

    def test_resume_rejects_changed_file_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = api.APIClient(self.key, root / "first", opener=MockOpener([[self.row]]))
            original.fetch("getFcltyInfoDataList")
            next((root / "first").glob("*.records.jsonl")).write_text('{}\n')
            opener = MockOpener([])
            resumed = api.APIClient(self.key, root / "second", opener=opener, resume_from=root / "first")
            with self.assertRaises(api.CollectionError):
                resumed.fetch("getFcltyInfoDataList")
            self.assertEqual(opener.urls, [])

    def test_resume_does_not_reuse_different_request_parameters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = api.APIClient(self.key, root / "first", opener=MockOpener([[]]))
            original.fetch("getFcltyDateInfoData", fcltyId="F1", fcltyYear="2024")
            opener = MockOpener([[]])
            resumed = api.APIClient(self.key, root / "second", opener=opener, resume_from=root / "first")
            resumed.fetch("getFcltyDateInfoData", fcltyYear="2023", fcltyId="F1")
            self.assertEqual(len(opener.urls), 1)
            self.assertEqual(resumed.network_requests, 1)

    def test_default_request_interval_is_enforced_between_network_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = api.APIClient(self.key, Path(temporary) / "run", opener=MockOpener([[], []]))
            with patch.object(api.time, "monotonic", side_effect=[10.0, 10.2, 11.0]):
                client.fetch("getFcltyInfoDataList")
                client.fetch("getFcltyDateInfoData", fcltyId="F1", fcltyYear="2024")
            self.assertAlmostEqual(self.sleep.call_args.args[0], 0.8)

    def test_request_budget_returns_partial_exit_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            opener = MockOpener([[{"fcltyId": "F1", "fcltyYear": "2024"}]])
            with patch.dict(os.environ, {"SMARTFARM_API_KEY": self.key}), patch.object(api, "build_opener", return_value=opener):
                with contextlib.redirect_stderr(io.StringIO()):
                    result = api.main(["--output-root", temporary, "--max-requests", "1"])
            self.assertEqual(result, 3)
            manifest = json.loads(next(Path(temporary).glob("*/manifest.json")).read_text())
            self.assertEqual(manifest["status"], "truncated")
            self.assertEqual(manifest["limit_reasons"], ["max_requests"])
            self.assertEqual(manifest["network_request_count"], 1)

    def test_no_key_exits_two_without_network_or_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "should_not_exist"
            with patch.dict(os.environ, {}, clear=True), patch.object(api, "build_opener") as opener:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = api.main(["--output-root", str(path)])
                self.assertEqual(code, 2)
                opener.assert_not_called()
                self.assertFalse(path.exists())

    def test_timeseries_requires_dates_before_network(self):
        with patch.object(api, "build_opener") as opener, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                api.main(["--include-timeseries"])
            self.assertEqual(error.exception.code, 2)
            opener.assert_not_called()

    def test_unexpected_exception_is_not_printed_with_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            stderr = io.StringIO()
            with patch.dict(os.environ, {"SMARTFARM_API_KEY": self.key}):
                with patch.object(api, "collect", side_effect=RuntimeError("https://host/" + self.key)):
                    with contextlib.redirect_stderr(stderr):
                        result = api.main(["--output-root", temporary])
            self.assertEqual(result, 1)
            self.assertNotIn(self.key, stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            manifest = next(Path(temporary).glob("*/manifest.json"))
            self.assertEqual(json.loads(manifest.read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
