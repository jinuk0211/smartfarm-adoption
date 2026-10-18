"""Exercise the facility calculation UI against the real model and budget engine."""

from pathlib import Path
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest


PROJECT = Path(__file__).resolve().parents[1]


def facility_page(project):
    from pathlib import Path
    from src.farm_economics_ui import render_facility_calculator

    render_facility_calculator(Path(project))


def open_page():
    return AppTest.from_function(facility_page, args=(str(PROJECT),), default_timeout=30).run()


def example_page():
    app = open_page()
    app.button(key="fe_example").click().run()
    assert not app.exception
    return app


def test_default_route_is_target_facility_and_money_is_not_prefilled():
    required = [PROJECT / "data/processed" / name for name in (
        "rda_crop_income.csv", "kamis_wholesale_monthly_kg.csv",
    )]
    missing = [str(path.relative_to(PROJECT)) for path in required if not path.is_file()]
    if missing:
        pytest.skip("Full-app local CSVs are required: " + ", ".join(missing))
    app = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.radio(key="calculation_route").value == "내 시설 계획으로 계산"
    assert app.number_input(key="fe_sales_0_price").value is None
    assert app.number_input(key="fe_costs_energy_water").value is None
    assert app.number_input(key="fe_investment_0_amount").value is None
    assert app.button(key="fe_calculate").disabled
    assert not any(widget.key == "capex" for widget in app.number_input)


def test_explicit_fictional_example_computes_income_cash_and_payback():
    app = example_page()
    assert any("가상 입력 예시" in item.value for item in app.warning)
    assert not app.button(key="fe_calculate").disabled, [item.value for item in app.info]
    app.button(key="fe_calculate").click().run()
    assert not app.exception
    payload = app.session_state["facility_calculation_payload"]
    result = app.session_state["facility_calculation_result"]
    base = next(row for row in result["scenarios"] if row["name"] == "기준")
    assert payload["prediction"]["target"] == "shipment"
    assert payload["prediction"]["query"]["area_m2"] == 1000
    assert base["annual_revenue_krw"] == pytest.approx(payload["prediction"]["prediction"] * 10000)
    assert base["annual_income_after_family_labor_krw"] == pytest.approx(base["annual_revenue_krw"] - 23500000)
    assert base["annual_incremental_cash_flow_before_replacements_krw"] == pytest.approx(base["annual_revenue_krw"] - 12500000)
    assert base["cash_flows_krw"][0] == -100000000
    assert {row["source_kind"] for row in payload["costs"]} == {"budget"}
    assert payload["evidence_target"] == payload["target"]
    assert len(app.metric) >= 5


@pytest.mark.parametrize("widget, changed", [("fe_facility_id", "다른시설"), ("fe_plan_id", "다른계획")])
def test_target_change_does_not_silently_rebind_existing_evidence(widget, changed):
    app = example_page()
    app.button(key="fe_calculate").click().run()
    app.text_input(key=widget).set_value(changed).run()
    assert not app.exception
    assert app.button(key="fe_calculate").disabled
    assert "facility_calculation_result" not in app.session_state
    assert app.session_state["facility_evidence_target"][widget.removeprefix("fe_")] != changed
    assert any("입력이 변경" in item.value for item in app.info)


def test_area_change_requires_scope_reconnection_then_recalculates_prediction():
    app = example_page()
    app.button(key="fe_calculate").click().run()
    before = app.session_state["facility_calculation_payload"]["prediction"]["prediction"]
    app.number_input(key="fe_area").set_value(2000.0).run()
    assert app.button(key="fe_calculate").disabled
    assert "facility_calculation_result" not in app.session_state
    app.button(key="fe_bind_scope").click().run()
    assert not app.button(key="fe_calculate").disabled
    app.button(key="fe_calculate").click().run()
    after = app.session_state["facility_calculation_payload"]
    assert after["evidence_target"]["area_m2"] == 2000
    assert after["prediction"]["query"]["area_m2"] == 2000
    assert after["prediction"]["prediction"] != before


def test_price_change_hides_stale_result_and_missing_cost_is_not_zero():
    app = example_page()
    app.button(key="fe_calculate").click().run()
    original = app.session_state["facility_calculation_result"]["scenarios"][1]["annual_revenue_krw"]
    app.number_input(key="fe_sales_0_price").set_value(8000.0).run()
    assert "facility_calculation_result" not in app.session_state
    app.button(key="fe_calculate").click().run()
    assert app.session_state["facility_calculation_result"]["scenarios"][1]["annual_revenue_krw"] == pytest.approx(original * .8)
    app.number_input(key="fe_costs_rent").set_value(None).run()
    assert app.button(key="fe_calculate").disabled
    assert "facility_calculation_result" not in app.session_state
    app.number_input(key="fe_costs_rent").set_value(0.0).run()
    assert not app.button(key="fe_calculate").disabled


def test_reverting_an_edited_input_still_requires_a_fresh_calculation():
    app = example_page()
    app.button(key="fe_calculate").click().run()
    app.number_input(key="fe_sales_0_price").set_value(8000.0).run()
    app.number_input(key="fe_sales_0_price").set_value(10000.0).run()
    assert not app.exception
    assert "facility_calculation_result" not in app.session_state
    assert not any(metric.label == "연간 매출" for metric in app.metric)


def test_first_payback_does_not_hide_later_replacement_loss():
    app = example_page()
    app.number_input(key="fe_sales_0_price").set_value(1000000.0)
    app.number_input(key="fe_investment_0_amount").set_value(1000000.0)
    app.radio(key="fe_replacement_policy").set_value("교체 계획 입력").run()
    app.number_input(key="fe_replacement_0_year").set_value(2)
    app.number_input(key="fe_replacement_0_amount").set_value(1000000000000.0).run()
    app.button(key="fe_calculate").click().run()
    assert not app.exception
    base = app.session_state["facility_calculation_result"]["scenarios"][1]
    assert base["payback_year"] == 1
    assert not base["recovered_by_horizon"]
    assert any("다시 미회수 상태" in item.value for item in app.warning)


def test_retrofit_needs_same_facility_baseline_inputs():
    app = example_page()
    app.selectbox(key="fe_mode").set_value("기존 시설 개량").run()
    assert not app.exception
    assert app.button(key="fe_calculate").disabled
    assert app.number_input(key="fe_baseline_yield").value is None
    assert app.number_input(key="fe_baseline_costs_energy_water").value is None
    assert app.number_input(key="fe_baseline_sales_0_price").value is None
    app.selectbox(key="fe_baseline_source_kind").set_value("직접 세운 계획")
    app.text_input(key="fe_baseline_source_ref").set_value("테스트용 가상 유지 계획")
    app.number_input(key="fe_baseline_yield").set_value(3000.0)
    app.text_input(key="fe_baseline_sales_0_label").set_value("가상 유지안 판매")
    app.number_input(key="fe_baseline_sales_0_share").set_value(100.0)
    app.number_input(key="fe_baseline_sales_0_price").set_value(10000.0)
    app.date_input(key="fe_baseline_sales_0_start").set_value(date(2026, 12, 1))
    app.date_input(key="fe_baseline_sales_0_end").set_value(date(2027, 6, 30))
    app.selectbox(key="fe_baseline_sales_0_source_kind").set_value("직접 세운 계획")
    app.text_input(key="fe_baseline_sales_0_source_ref").set_value("가상 유지안 판매 가정")
    app.selectbox(key="fe_baseline_costs_source_kind").set_value("직접 세운 계획")
    app.text_input(key="fe_baseline_costs_source_ref").set_value("가상 유지안 비용 가정")
    from src.farm_economics_ui import COST_LABELS

    for category in COST_LABELS:
        app.number_input(key=f"fe_baseline_costs_{category}").set_value(
            app.number_input(key=f"fe_costs_{category}").value)
    app.radio(key="fe_baseline_replacement_policy").set_value("없음으로 계획").run()
    assert not app.exception
    assert not app.button(key="fe_calculate").disabled
    app.button(key="fe_calculate").click().run()
    result = app.session_state["facility_calculation_result"]
    base = next(row for row in result["scenarios"] if row["name"] == "기준")
    assert result["mode"] == "retrofit"
    assert base["annual_incremental_cash_flow_before_replacements_krw"] == pytest.approx(
        base["annual_cash_surplus_before_replacements_krw"] - (30000000 - 12500000))
