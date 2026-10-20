"""Causal cutoffs and source identity checks for DSZ observation features."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from src.dsz_data import load_schema, validate_table
from src.dsz_observations import (
    OBSERVATION_NUMERIC, build_observation_features, load_observation_tables,
)


@pytest.fixture
def schema():
    return load_schema()


def raw_table(schema, table_id, records):
    columns = [column["name"] for column in schema["tables"][table_id]["columns"]]
    frame = pd.DataFrame([{**dict.fromkeys(columns, ""), **record} for record in records], columns=columns)
    frame = frame.fillna("").astype(str)
    frame["_source_file"] = f"{table_id}.csv"
    frame["_source_row"] = range(2, len(frame) + 2)
    return frame


def validated(schema, tables):
    return {key: validate_table(key, raw_table(schema, key, records), schema["tables"][key])[0]
            for key, records in tables.items()}


def facility(number="1", farm="F1", start="20240101", end="20240331", **extra):
    return {"FRMTM_SNO": number, "FCLT_ID": farm, "FRMTM_YR": start[:4],
            "FRMTM_BGNG_YMD": start, "FRMTM_END_YMD": end, "ITEM_NM": "딸기",
            "AREA_NM": "경북", "SACT_INTLCK_SPR_NM": "단동", "HTHS_SCL_CN": "중형",
            "HTHS_SFC": "1000", **extra}


def environment(time="2024-01-20 12:00:00", farm="F1", year="2024", **extra):
    return {"FCLT_ID": farm, "FRMTM_YR": year, "MSRM_DT": time,
            "INR_TMPRT_MRCNT": "20", "INR_HMDT_MRCNT": "60", **extra}


def growth(date="20240120", sample="1", **extra):
    return {"FCLT_ID": "F1", "FRMTM_YR": "2024", "EXMN_YMD": date,
            "SMPL_SNO": sample, "GRDV_NOFWK": "3", **extra}


def weather(date="20240120", station="A", **extra):
    return {"FCLT_ID": "F1", "OBSV_YMD": date, "OBSV_PNT_CDCN": station, **extra}


def requests(*keys):
    return pd.DataFrame(keys or [("request1", "F1", "1")], columns=["row_id", "facility_id", "cycle_id"])


def test_other_facility_other_cycle_and_year_mismatch_do_not_enter_features(schema):
    tables = validated(schema, {
        "DZ_002": [facility(), facility("2", "F1", "20231001", "20231231"), facility("3", "F2")],
        "DZ_001": [environment(), environment("2023-12-20", year="2023", INR_TMPRT_MRCNT="99"),
                   environment(farm="F2", INR_TMPRT_MRCNT="88"),
                   environment("2024-01-21", year="2023", INR_TMPRT_MRCNT="77")],
    })
    frame, audit = build_observation_features(tables, requests(), 30)
    assert frame.loc[0, "env_inside_temperature_c_window_mean"] == 20
    assert frame.loc[0, "env_observation_rows"] == 1
    assert audit["observation_exclusions"]["DZ_001"]["observation_cycle_year_mismatch"] == 1


def test_future_rows_and_bulk_loading_time_do_not_change_features(schema):
    source = {"DZ_002": [facility()], "DZ_001": [environment()],
              "DZ_003": [growth(FLVS_MMUNT_MRCNT="100")],
              "DZ_005": [weather(TOP_TMPRT_MSRVL="25")]}
    before, _ = build_observation_features(validated(schema, source), requests(), 30)
    changed = deepcopy(source)
    changed["DZ_001"][0]["STR_DT"] = "2029-01-01"
    changed["DZ_001"].append(environment("2024-02-01", INR_TMPRT_MRCNT="999"))
    changed["DZ_003"].append(growth("20240201", FLVS_MMUNT_MRCNT="999"))
    changed["DZ_005"].append(weather("20240201", TOP_TMPRT_MSRVL="999"))
    after, _ = build_observation_features(validated(schema, changed), requests(), 30)
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("other", [facility("2", start="20240115"),
                                    facility("2", start="20240115", HTHS_SFC="not a number")])
def test_raw_overlap_is_rejected_even_if_other_cycle_has_invalid_values(schema, other):
    tables = validated(schema, {"DZ_002": [facility(), other], "DZ_001": [environment()]})
    frame, audit = build_observation_features(tables, requests(), 30)
    assert frame.empty
    assert audit["excluded_requests"][0]["reason"] == "overlapping_cycles_in_raw_facility_table"


def test_growth_uses_visit_sample_means_and_change_between_visits(schema):
    tables = validated(schema, {
        "DZ_002": [facility()],
        "DZ_003": [growth("20240110", "1", FLVS_MMUNT_MRCNT="100", DMTR_MMUNT_MRCNT="10", FSTNG_MRCNT="2"),
                   growth("20240110", "2", FLVS_MMUNT_MRCNT="200", DMTR_MMUNT_MRCNT="20", FSTNG_MRCNT="4"),
                   growth("20240120", "3", FLVS_MMUNT_MRCNT="220", DMTR_MMUNT_MRCNT="22", FSTNG_MRCNT="6"),
                   growth("20240120", "4", FLVS_MMUNT_MRCNT="260", DMTR_MMUNT_MRCNT="26", FSTNG_MRCNT="8")],
    })
    frame, audit = build_observation_features(tables, requests(), 30)
    row = frame.iloc[0]
    assert row.growth_height_mm_latest_mean == 240
    assert row.growth_height_mm_visit_mean_delta == 90
    assert row.growth_crown_diameter_mm_visit_mean_delta == 9
    assert row.growth_fruit_count_visit_mean_delta == 4
    assert row.growth_latest_sample_rows == 2
    assert row.growth_visit_count == 2
    assert row.growth_days_since_latest_visit == 11
    assert any("not tracked individual" in text for text in audit["assumptions"])


def test_daily_cutoff_day_is_excluded_but_exact_timestamp_is_included(schema):
    tables = validated(schema, {
        "DZ_002": [facility()],
        "DZ_001": [environment("2024-01-31 00:00:00", INR_TMPRT_MRCNT="21"),
                   environment("2024-01-31 00:00:01", INR_TMPRT_MRCNT="99")],
        "DZ_003": [growth("20240130", FLVS_MMUNT_MRCNT="200"), growth("20240131", FLVS_MMUNT_MRCNT="999")],
        "DZ_005": [weather("20240130", TOP_TMPRT_MSRVL="20"), weather("20240131", TOP_TMPRT_MSRVL="99")],
    })
    frame, _ = build_observation_features(tables, requests(), 30)
    assert frame.loc[0, "env_inside_temperature_c_window_mean"] == 21
    assert frame.loc[0, "growth_height_mm_latest_mean"] == 200
    assert frame.loc[0, "weather_max_temperature_c_window_mean"] == 20


def test_weather_averages_stations_within_day_before_days(schema):
    tables = validated(schema, {
        "DZ_002": [facility()],
        "DZ_005": [weather("20240120", "A", TOP_TMPRT_MSRVL="10"),
                   weather("20240120", "B", TOP_TMPRT_MSRVL="30"),
                   weather("20240121", "A", TOP_TMPRT_MSRVL="50")],
    })
    frame, _ = build_observation_features(tables, requests(), 30)
    assert frame.loc[0, "weather_max_temperature_c_window_mean"] == 35
    assert frame.loc[0, "weather_observed_days"] == 2


def test_absent_observation_values_stay_nan_with_separate_zero_coverage(schema):
    frame, _ = build_observation_features(validated(schema, {"DZ_002": [facility()]}), requests(), 30)
    assert np.isnan(frame.loc[0, "env_inside_temperature_c_window_mean"])
    assert np.isnan(frame.loc[0, "growth_height_mm_latest_mean"])
    assert np.isnan(frame.loc[0, "growth_days_since_latest_visit"])
    assert frame.loc[0, "env_observation_rows"] == 0
    assert not frame.loc[0, "has_observations"]
    assert set(OBSERVATION_NUMERIC).issubset(frame.columns)


def test_invalid_numeric_cell_does_not_erase_other_valid_measurements(schema):
    tables = validated(schema, {"DZ_002": [facility()],
                               "DZ_001": [environment(INR_TMPRT_MRCNT="invalid")]})
    frame, _ = build_observation_features(tables, requests(), 30)
    assert np.isnan(frame.loc[0, "env_inside_temperature_c_window_mean"])
    assert frame.loc[0, "env_inside_humidity_pct_window_mean"] == 60
    assert frame.loc[0, "has_observations"]


def test_growth_week_key_alone_does_not_claim_measured_growth(schema):
    tables = validated(schema, {"DZ_002": [facility()], "DZ_003": [growth()]})
    frame, _ = build_observation_features(tables, requests(), 30)
    assert frame.loc[0, "growth_week_latest_mean"] == 3
    assert not frame.loc[0, "has_observations"]


def test_duplicate_observation_pk_is_excluded_and_duplicate_facility_is_not_unique(schema):
    tables = validated(schema, {"DZ_002": [facility()], "DZ_001": [environment(), environment()]})
    frame, audit = build_observation_features(tables, requests(), 30)
    assert not frame.loc[0, "has_observations"]
    assert audit["observation_exclusions"]["DZ_001"]["invalid_or_duplicate_observation_key"] == 2
    duplicated = validated(schema, {"DZ_002": [facility(), facility(number="1.0")]})
    frame, audit = build_observation_features(duplicated, requests(), 30)
    assert frame.empty
    assert audit["excluded_requests"][0]["reason"] == "missing_or_nonunique_facility_cycle_key"


def test_request_order_and_one_to_one_output_are_preserved(schema):
    tables = validated(schema, {"DZ_002": [facility(), facility("2", "F2")]})
    frame, _ = build_observation_features(tables, requests(("b", "F2", "2"), ("a", "F1", "1")), 30)
    assert frame.row_id.tolist() == ["b", "a"]
    assert frame.row_id.is_unique
    with pytest.raises(ValueError, match="row_id unique"):
        build_observation_features(tables, requests(("a", "F1", "1"), ("a", "F2", "2")), 30)


def test_finished_cycle_rejects_late_cutoff_and_ongoing_query_allows_blank_end(schema):
    tables = validated(schema, {"DZ_002": [facility(end="20240130"), facility("2", "F2", end="")]})
    frame, audit = build_observation_features(tables, requests(("a", "F1", "1"), ("b", "F2", "2")), 30)
    assert frame.row_id.tolist() == ["b"]
    assert audit["excluded_requests"][0]["reason"] == "cutoff_after_cycle_end"


def test_loader_accepts_query_without_management_and_reports_invalid_cells(schema, tmp_path):
    for key, records in {"DZ_002": [facility()], "DZ_001": [environment(INR_TMPRT_MRCNT="bad")]}.items():
        frame = raw_table(schema, key, records).drop(columns=["_source_file", "_source_row"])
        frame.to_csv(tmp_path / f"{key}.csv", index=False, encoding="utf-8-sig")
    tables, sources, issues = load_observation_tables(tmp_path)
    assert set(tables) == {"DZ_001", "DZ_002"}
    assert len(sources) == 2
    assert any(issue["reason"] == "invalid_number" for issue in issues)
    assert load_schema()["tables"]["DZ_004"]["required"]


def test_typhoon_is_audit_only_and_alerts_count_published_rows_not_events(schema):
    tables = validated(schema, {
        "DZ_002": [facility()],
        "DZ_006": [{"FCLT_ID": "F1", "OBSV_PNT_CDCN": "A", "PRSTN_DT": "2024-01-30", "PRSTN_CN": "주의보"},
                   {"FCLT_ID": "F1", "OBSV_PNT_CDCN": "B", "PRSTN_DT": "2024-01-30", "PRSTN_CN": "주의보"},
                   {"FCLT_ID": "F1", "OBSV_PNT_CDCN": "A", "PRSTN_DT": "2024-02-01", "PRSTN_CN": "주의보"}],
        "DZ_007": [{"FCLT_ID": "F1", "OBSV_PNT_CDCN": "A", "TPHN_ENG_NM": "EXAMPLE", "OBSV_DT": "2024-01-20"}],
    })
    frame, audit = build_observation_features(tables, requests(), 30)
    assert frame.loc[0, "alerts_published_row_count"] == 2
    assert not frame.loc[0, "has_observations"]
    assert not any("typhoon" in name for name in OBSERVATION_NUMERIC)
    assert audit["observation_exclusions"]["DZ_007"]["audit_only_no_publication_time"] == 1
