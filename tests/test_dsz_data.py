"""Synthetic tests for exact DSZ joins, units, missingness and declared assumptions."""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src import dsz_data as dsz


class DSZPreparationTests(unittest.TestCase):
    def setUp(self):
        self.schema = dsz.load_schema()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = Path(self.tmp.name) / "input"
        self.output = Path(self.tmp.name) / "output"
        self.input.mkdir()

    def row(self, table_id, **changes):
        record = {column["name"]: "" for column in self.schema["tables"][table_id]["columns"]}
        record.update(STR_DT="2022-01-01 00:00:00", STR_USERID="TEST")
        if table_id == "DZ_002":
            record.update(FRMTM_SNO="00001", FRMTM_YR="2021", FCLT_ID="00017", ITEM_NM="딸기",
                          AREA_NM="경남", SACT_INTLCK_SPR_NM="연동", HTHS_SCL_CN="2동",
                          FRMTM_BGNG_YMD="20210101", FRMTM_END_YMD="20211231", HTHS_SFC="1000.250")
        elif table_id == "DZ_004":
            record.update(EXMN_SNO="00002", EXMN_YMD="20211231", FCLT_ID="00017", ALL_SHPMNT_KGUNT_QTY="0", ALL_INCM_AMT="1000.50")
        record.update(changes)
        return record

    def write(self, facilities=None, surveys=None, encoding="utf-8-sig", xlsx=False):
        for table_id, records in {"DZ_002": facilities if facilities is not None else [self.row("DZ_002")],
                                  "DZ_004": surveys if surveys is not None else [self.row("DZ_004")]}.items():
            path = self.input / (self.schema["tables"][table_id]["filename"] + (".xlsx" if xlsx else ".csv"))
            frame = pd.DataFrame(records)
            if xlsx:
                frame.to_excel(path, index=False)
            else:
                frame.to_csv(path, index=False, encoding=encoding)

    def run_prep(self, **kwargs):
        manifest = dsz.prepare(self.input, self.output, **kwargs)
        return manifest, pd.read_csv(self.output / "dsz_model_candidates.csv", dtype={"facility_id": str, "cycle_id": str}, keep_default_na=False)

    def test_exact_keys_ids_zero_units_and_source_provenance(self):
        self.write()
        manifest, data = self.run_prep()
        self.assertEqual(len(data), 1)
        self.assertEqual(data.loc[0, "facility_id"], "00017")
        self.assertEqual(data.loc[0, "cycle_id"], "00001")
        self.assertEqual(data.loc[0, "area_m2"], 1000.25)
        self.assertEqual(data.loc[0, "reported_shipment_kg"], 0)
        self.assertTrue(data.loc[0, "shipment_eligible"])
        self.assertEqual(json.loads(data.loc[0, "management_raw_json"])[0]["EXMN_SNO"], "00002")
        self.assertFalse(manifest["target_period_confirmed"])

    def test_target_eligibility_is_independent_missing_is_not_zero(self):
        self.write(surveys=[self.row("DZ_004", ALL_SHPMNT_KGUNT_QTY="", ALL_INCM_AMT="0")])
        _, data = self.run_prep()
        self.assertEqual(data.loc[0, "reported_shipment_kg"], "")
        self.assertFalse(data.loc[0, "shipment_eligible"])
        self.assertTrue(data.loc[0, "revenue_eligible"])
        self.assertEqual(data.loc[0, "reported_revenue_krw"], 0)

    def test_cp949_and_xlsx_keep_text_ids(self):
        for encoding, xlsx in [("cp949", False), ("utf-8-sig", True)]:
            with self.subTest(encoding=encoding, xlsx=xlsx):
                for path in self.input.iterdir():
                    path.unlink()
                self.write(encoding=encoding, xlsx=xlsx)
                _, data = self.run_prep(encoding=encoding)
                self.assertEqual(data.loc[0, "facility_id"], "00017")
                self.assertEqual(data.loc[0, "crop"], "딸기")

    def test_overlapping_cycle_and_shared_boundary_are_ambiguous(self):
        self.write(facilities=[self.row("DZ_002"), self.row("DZ_002", FRMTM_SNO="2", FRMTM_BGNG_YMD="20211231")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertEqual(manifest["exclusion_reason_counts"]["ambiguous_cycle_match"], 1)

    def test_ambiguous_extra_survey_does_not_create_false_singleton(self):
        self.write(facilities=[self.row("DZ_002"), self.row("DZ_002", FRMTM_SNO="2", FRMTM_BGNG_YMD="20210601")],
                   surveys=[self.row("DZ_004", EXMN_YMD="20210501"), self.row("DZ_004", EXMN_SNO="3")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertIn("cycle_contains_invalid_survey", manifest["exclusion_reason_counts"])

    def test_unmatched_date_and_other_facility_not_joined(self):
        self.write(surveys=[self.row("DZ_004", EXMN_YMD="20200101"), self.row("DZ_004", EXMN_SNO="3", FCLT_ID="17")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertEqual(manifest["exclusion_reason_counts"]["unmatched_eligible_cycle"], 2)

    def test_duplicate_and_conflicting_survey_primary_keys_not_summed(self):
        for second in [self.row("DZ_004"), self.row("DZ_004", ALL_INCM_AMT="999")]:
            with self.subTest(second=second):
                self.write(surveys=[self.row("DZ_004"), second])
                manifest, data = self.run_prep(management_policy="incremental_sum")
                self.assertTrue(data.empty)
                self.assertTrue(any("primary_key" in reason for reason in manifest["validation_issue_counts"]))

    def test_missing_primary_key_excludes_cycle_even_with_good_survey(self):
        self.write(surveys=[self.row("DZ_004"), self.row("DZ_004", EXMN_SNO="")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertIn("cycle_contains_invalid_survey", manifest["exclusion_reason_counts"])

    def test_multiple_surveys_require_explicit_policy(self):
        self.write(surveys=[self.row("DZ_004", ALL_SHPMNT_KGUNT_QTY="10", EXMN_YMD="20211101"),
                            self.row("DZ_004", EXMN_SNO="3", ALL_SHPMNT_KGUNT_QTY="20")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertIn("multiple_surveys_no_aggregation", manifest["exclusion_reason_counts"])
        manifest, data = self.run_prep(management_policy="incremental_sum")
        self.assertEqual(data.loc[0, "reported_shipment_kg"], 30)
        self.assertEqual(manifest["target_assumption"], "incremental_sum")
        self.assertEqual(len(json.loads(data.loc[0, "management_raw_json"])), 2)
        _, data = self.run_prep(management_policy="latest_cumulative")
        self.assertEqual(data.loc[0, "reported_shipment_kg"], 20)

    def test_sum_never_partially_fills_missing_target(self):
        self.write(surveys=[self.row("DZ_004", ALL_SHPMNT_KGUNT_QTY="10"), self.row("DZ_004", EXMN_SNO="3", ALL_SHPMNT_KGUNT_QTY="")])
        _, data = self.run_prep(management_policy="incremental_sum")
        self.assertFalse(data.loc[0, "shipment_eligible"])
        self.assertEqual(data.loc[0, "reported_shipment_kg"], "")
        self.assertEqual(data.loc[0, "reported_revenue_krw"], 2001)

    def test_cumulative_latest_date_tie_is_not_arbitrarily_chosen(self):
        self.write(surveys=[self.row("DZ_004"), self.row("DZ_004", EXMN_SNO="3")])
        manifest, data = self.run_prep(management_policy="latest_cumulative")
        self.assertTrue(data.empty)
        self.assertIn("ambiguous_latest_survey_date", manifest["exclusion_reason_counts"])

    def test_synthetic_detection_and_mixed_source_rejection(self):
        self.write(facilities=[self.row("DZ_002", FCLT_ID="SYN_FARM_001")], surveys=[self.row("DZ_004", FCLT_ID="SYN_FARM_001")])
        manifest, data = self.run_prep()
        self.assertEqual(manifest["data_kind"], "synthetic_schema_fixture")
        self.assertTrue(data["data_kind"].eq("synthetic_schema_fixture").all())
        self.write(facilities=[self.row("DZ_002", FCLT_ID="SYN_FARM_001")], surveys=[self.row("DZ_004")])
        with self.assertRaisesRegex(ValueError, "must not be mixed"):
            self.run_prep()

    def test_future_columns_and_optional_measurements_never_change_features(self):
        facility = self.row("DZ_002")
        self.write(facilities=[facility])
        _, baseline = self.run_prep()
        facility["FRMTM_END_YMD"] = "20211230"
        self.write(facilities=[facility], surveys=[self.row("DZ_004", EXMN_YMD="20211229", ALL_INCM_AMT="9999")])
        environment = self.row("DZ_001", FRMTM_YR="2021", FCLT_ID="00017", MSRM_DT="2021-10-01", INR_TMPRT_MRCNT="99")
        pd.DataFrame([environment]).to_csv(self.input / "DZ_001.csv", index=False, encoding="utf-8-sig")
        manifest, changed = self.run_prep()
        pd.testing.assert_frame_equal(baseline[dsz.FEATURES], changed[dsz.FEATURES])
        self.assertEqual(manifest["inventory"]["DZ_001"]["model_usage"], "inventory_only_never_model_features")

    def test_schema_wrong_names_and_declared_types_are_validated(self):
        self.write(surveys=[self.row("DZ_004", ALL_SHPMNT_KGUNT_QTY="2.5")])
        manifest, data = self.run_prep()
        self.assertFalse(data.loc[0, "shipment_eligible"])
        self.assertTrue(data.loc[0, "revenue_eligible"])
        self.assertIn("number_precision_or_scale", manifest["validation_issue_counts"])
        path = self.input / "M_DZ_SFARMMANAGEMENT.csv"
        frame = pd.read_csv(path).rename(columns={"EXMN_SNO": "임의번역"})
        frame.to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "missing exact named columns"):
            self.run_prep()

    def test_numeric_primary_key_equivalent_encodings_conflict(self):
        self.write(surveys=[self.row("DZ_004"), self.row("DZ_004", EXMN_SNO="2")])
        manifest, data = self.run_prep(management_policy="incremental_sum")
        self.assertTrue(data.empty)
        self.assertEqual(manifest["validation_issue_counts"]["conflicting_primary_key"], 2)

    def test_unplaceable_survey_does_not_make_other_record_a_false_singleton(self):
        self.write(surveys=[self.row("DZ_004"), self.row("DZ_004", EXMN_SNO="3", EXMN_YMD="20210230")])
        manifest, data = self.run_prep()
        self.assertTrue(data.empty)
        self.assertIn("cycle_contains_invalid_survey", manifest["exclusion_reason_counts"])

    def test_decimal_precision_validation_does_not_round_or_underflow(self):
        column = next(col for col in self.schema["tables"]["DZ_004"]["columns"] if col["name"] == "ALL_INCM_AMT")
        for value in ["1e-999999999", "1e999999999", "1_000", "NaN", "Infinity"]:
            self.assertIsNotNone(dsz.type_error(value, column), value)
        self.assertIsNone(dsz.type_error("1000.00", column))

    def test_dictionary_hash_and_presence_are_verified_before_preparation(self):
        self.write()
        custom_schema = Path(self.tmp.name) / "schema.json"
        for change in [{"dictionary_sha256": "0" * 64},
                       {"dictionary_path": str(Path(self.tmp.name) / "missing_dictionary.txt")}]:
            with self.subTest(change=change):
                schema = dict(self.schema, **change)
                custom_schema.write_text(json.dumps(schema), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Source dictionary is missing or its SHA256 differs"):
                    self.run_prep(schema_path=custom_schema)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
