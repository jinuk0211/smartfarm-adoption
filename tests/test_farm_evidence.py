from pathlib import Path

import pytest

from src.farm_evidence import audit_api_links, audit_public_cases, load_farm_evidence


def cycle(facility="F1", number="1", year="2023", crop="딸기"):
    return {"fcltyId": facility, "crpsnSn": number, "fcltyYear": year, "itemCodeNm": crop}


def record(facility="F1", number="1"):
    return {"fcltyId": facility, "crpsnSn": number}


def test_same_facility_different_cycle_cannot_supply_cost():
    evidence = audit_api_links([cycle(), cycle(number="2")], [record()], [record(number="2")])
    assert evidence["counts"]["overlap_cycles"] == 0
    original = next(row for row in evidence["cycle_evidence"] if row["cycle_number"] == "1")
    assert original["cost_record_status"] == "not_observed"
    assert original["verified_total_operating_cost_krw"] is None
    assert original["verified_income_krw"] is None


def test_ambiguous_year_cannot_be_resolved_from_derived_audit_column():
    row = {**record(), "audit_fcltyYear": "2023"}
    evidence = audit_api_links([cycle(), cycle(year="2024")], [row], [row])
    assert evidence["counts"]["overlap_cycles"] == 0
    assert evidence["rejected_rows"]["output"] == {"ambiguous_cycle_year_or_metadata": 1}


def test_grouped_join_preserves_record_counts_without_cartesian_product():
    evidence = audit_api_links([cycle()], [record()] * 3, [record()] * 2)
    assert evidence["counts"]["overlap_cycles"] == 1
    row = evidence["cycle_evidence"][0]
    assert (row["output_rows"], row["cost_rows"]) == (3, 2)
    assert row["verified_total_operating_cost_krw"] is None
    assert not evidence["complete_cost_verified"]


def test_missing_cycle_key_never_falls_back_to_facility():
    evidence = audit_api_links([cycle()], [{"fcltyId": "F1"}], [record()])
    assert evidence["counts"]["overlap_cycles"] == 0
    assert evidence["rejected_rows"]["output"] == {"missing_facility_or_cycle": 1}


def test_income_identity_is_recomputed_not_trusted_from_cached_flags():
    row = {
        "case_id": "C1", "pilot_area_m2": "1600", "project_budget_krw": "20000000",
        "pilot_gross_revenue_1000krw_per_10a": "6500",
        "pilot_operating_cost_1000krw_per_10a": "1150",
        "pilot_reported_income_1000krw_per_10a": "30000",
        "nearby_gross_revenue_1000krw_per_10a": "5200",
        "nearby_operating_cost_1000krw_per_10a": "1500",
        "nearby_reported_income_1000krw_per_10a": "3700",
        "pilot_income_identity_difference_1000krw_per_10a": "0",
        "source_url": "https://example.org/source.pdf", "source_pdf_pages": "1",
        "source_sha256": "a" * 64,
    }
    evidence = audit_public_cases([row])
    assert not evidence["accepted_cases"]
    assert evidence["excluded_cases"][0]["reasons"] == ["pilot_income_identity_mismatch"]


def test_current_sources_include_one_arithmetic_valid_strawberry_case_but_no_roi():
    project = Path(__file__).resolve().parents[1]
    required = [project / "data/processed" / name for name in (
        "smartfarm_api_cycles.csv", "smartfarm_api_output.csv",
        "smartfarm_api_cost.csv", "public_farm_gg2023_cases.csv",
    )]
    missing = [str(path.relative_to(project)) for path in required if not path.is_file()]
    if missing:
        pytest.skip("Local evidence CSVs are required: " + ", ".join(missing))
    evidence = load_farm_evidence(project)
    public = evidence["public_cases"]
    assert len(public["accepted_cases"]) == 8
    assert {row["case_id"] for row in public["excluded_cases"]} == {
        "GG2023_SF_05", "GG2023_SF_08", "GG2023_SF_10", "GG2023_SF_12"
    }
    row, = public["strawberry_cases"]
    assert row["case_id"] == "GG2023_SF_03"
    assert row["area_m2"] == 1600
    assert (row["revenue_krw_per_1000m2"], row["operating_cost_krw_per_1000m2"], row["income_krw_per_1000m2"]) == (6_500_000, 1_150_000, 5_350_000)
    assert row["api_facility_id"] is None
    assert row["farm_total_capex_krw"] is None
    assert not row["training_eligible"]
    assert not row["annual_roi_validation_eligible"]
    assert evidence["api"]["counts"]["strawberry_overlap_cycles"] == 0
    assert all(len(item["sha256"]) == 64 for item in evidence["input_files"])


def test_case_arithmetic_does_not_validate_negative_revenue_or_missing_source():
    import csv

    path = Path(__file__).resolve().parents[1] / "data/processed/public_farm_gg2023_cases.csv"
    if not path.is_file():
        pytest.skip("Local evidence CSV is required: data/processed/public_farm_gg2023_cases.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        original = next(row for row in csv.DictReader(stream) if row["case_id"] == "GG2023_SF_03")
    row = dict(original, pilot_gross_revenue_1000krw_per_10a="-10",
               pilot_operating_cost_1000krw_per_10a="-5", pilot_reported_income_1000krw_per_10a="-5")
    result = audit_public_cases([row])
    assert not result["accepted_cases"]
    assert "pilot_negative_revenue_or_cost" in result["excluded_cases"][0]["reasons"]
    row = dict(original, source_url="", source_pdf_pages="", source_sha256="")
    result = audit_public_cases([row])
    assert not result["accepted_cases"]
    assert len(result["excluded_cases"][0]["reasons"]) == 3
    row = dict(original, pilot_area_ha="16")
    result = audit_public_cases([row])
    assert not result["accepted_cases"]
    assert "area_ha_m2_mismatch" in result["excluded_cases"][0]["reasons"]
