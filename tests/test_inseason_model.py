"""Behavioral guards for retrospective operational feature timing and linkage."""

import numpy as np
import pandas as pd
import pytest

from src.inseason_model import ENVIRONMENT_FEATURES, TARGET, build_cohort, evaluate


def fixtures():
    growth, environment = [], []
    for facility, offset in [("farm_a", 0), ("farm_b", 100)]:
        for day, height in [("2024-01-03", 80), ("2024-01-10", 100), ("2024-01-17", 110)]:
            growth.append({"시설ID": facility, "품목": "딸기", "조사일자": day,
                           "표본번호": 1, "항목명": "초장", "측정값": height + offset, "단위": "mm"})
        for day in pd.date_range("2024-01-01", "2024-01-20"):
            environment.append({"시설ID": facility, "품목": "딸기", "정식시작일": "2024-01-01",
                                "정식종료일": "2024-06-01", "분석일자": day,
                                "내부일평균온도": 10 + offset, "내부평균습도": 80, "CO2농도": 500})
    return pd.DataFrame(growth), pd.DataFrame(environment)


def visit(rows):
    return rows.loc[rows["farm_group"].eq("farm_a")
                    & rows["date"].eq(pd.Timestamp("2024-01-10"))].iloc[0]


def test_only_prior_same_facility_same_cycle_days_enter_features():
    growth, environment = fixtures()
    before, _ = build_cohort(growth, environment)
    environment.loc[(environment["시설ID"] == "farm_a")
                    & (environment["분석일자"] >= "2024-01-10"), "내부일평균온도"] = 9999
    after, _ = build_cohort(growth, environment)
    old, new = visit(before), visit(after)
    assert new["temperature_c_7d_mean"] == 10
    assert new["temperature_c_7d_count"] == 7
    assert new["temperature_c_28d_count"] == 9
    assert new["previous_height_delta_mm"] == 20
    assert new["previous_visit_gap_days"] == 7
    pd.testing.assert_series_equal(old[ENVIRONMENT_FEATURES], new[ENVIRONMENT_FEATURES])


def test_fixed_horizon_and_observed_sample_mean_not_same_plant():
    growth, environment = fixtures()
    growth.loc[growth["조사일자"] == "2024-01-17", "표본번호"] = 2
    extra = growth.iloc[[2]].copy()
    extra["표본번호"] = 3
    extra["측정값"] = 130
    rows, _ = build_cohort(pd.concat([growth, extra]), environment)
    pair = visit(rows)
    assert pair[TARGET] == 120
    assert (rows["next_date"] - rows["date"]).dt.days.eq(7).all()


def test_ambiguous_cycle_never_arbitrarily_selects_one():
    growth, environment = fixtures()
    overlap = environment[environment["시설ID"] == "farm_a"].copy()
    overlap["정식시작일"] = "2023-12-01"
    rows, audit = build_cohort(growth, pd.concat([environment, overlap]))
    assert set(rows["farm_group"]) == {"farm_b"}
    assert audit["visits_ambiguous_cycle"] == 3


def test_conflicting_day_and_sample_are_excluded_not_averaged():
    growth, environment = fixtures()
    bad_day = environment.iloc[[4]].copy()
    bad_day["내부일평균온도"] = 1000
    bad_sample = growth.iloc[[1]].copy()
    bad_sample["측정값"] = 999
    rows, audit = build_cohort(pd.concat([growth, bad_sample]), pd.concat([environment, bad_day]))
    assert audit["conflicting_growth_sample_rows_excluded"] == 2
    assert audit["conflicting_environment_day_rows_excluded"] == 2
    assert set(rows["farm_group"]) == {"farm_b"}
    rows, audit = build_cohort(growth, pd.concat([environment, bad_day]))
    pair = visit(rows)
    assert pair["temperature_c_7d_count"] == 6
    assert pair["temperature_c_7d_mean"] == 10


def test_unit_mismatch_cannot_be_silently_converted():
    growth, environment = fixtures()
    growth.loc[growth["시설ID"] == "farm_a", "단위"] = "cm"
    rows, _ = build_cohort(growth, environment)
    assert set(rows["farm_group"]) == {"farm_b"}


def test_missing_environment_remains_missing_with_zero_coverage():
    growth, environment = fixtures()
    environment["내부일평균온도"] = np.nan
    rows, _ = build_cohort(growth, environment)
    assert rows["temperature_c_7d_mean"].isna().all()
    assert rows["temperature_c_7d_count"].eq(0).all()


def test_cycle_boundary_breaks_pairs_and_previous_growth():
    growth, environment = fixtures()
    extra = growth.iloc[[2]].copy()
    extra["조사일자"] = "2024-01-24"
    extra["측정값"] = 120
    growth = pd.concat([growth, extra])
    farm_a = environment["시설ID"].eq("farm_a")
    prior = farm_a & environment["분석일자"].lt("2024-01-11")
    later = farm_a & ~prior
    environment.loc[prior, "정식종료일"] = "2024-01-10"
    environment.loc[later, "정식시작일"] = "2024-01-11"
    rows, _ = build_cohort(growth, environment)
    a = rows.loc[rows["farm_group"].eq("farm_a")]
    assert not a["date"].eq(pd.Timestamp("2024-01-10")).any()
    new_cycle = a.loc[a["date"].eq(pd.Timestamp("2024-01-17"))].iloc[0]
    assert pd.isna(new_cycle["previous_height_delta_mm"])
    assert new_cycle["temperature_c_28d_count"] == 6


def test_future_growth_target_changes_without_changing_current_features():
    growth, environment = fixtures()
    before, _ = build_cohort(growth, environment)
    growth.loc[growth["조사일자"].eq("2024-01-17"), "측정값"] = 900
    after, _ = build_cohort(growth, environment)
    columns = ENVIRONMENT_FEATURES + ["height_mm", "previous_height_delta_mm"]
    pd.testing.assert_series_equal(visit(before)[columns], visit(after)[columns])
    assert visit(before)[TARGET] != visit(after)[TARGET]


def test_no_pair_does_not_claim_a_completed_model():
    growth, environment = fixtures()
    growth["조사일자"] = "2024-01-10"
    with pytest.raises(ValueError, match="No visits|No exact"):
        build_cohort(growth, environment)


def test_facility_disjoint_predictions_and_persistence_baseline():
    growth, environment = fixtures()
    rows, _ = build_cohort(growth, environment)
    metrics, oof = evaluate(rows)
    assert len(metrics) == 4
    assert oof.groupby("farm_group")["fold"].nunique().eq(1).all()
    assert oof.groupby("fold")["farm_group"].nunique().eq(1).all()
    assert oof["current_height"].eq(oof["height_mm"]).all()
    assert all(np.isfinite(row["mae_mm"]) and row["n_scored"] == len(rows) for row in metrics)
