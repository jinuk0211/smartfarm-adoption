from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_missing_quote_disables_only_calculation_not_other_tabs():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["한눈에 보기", "도입 전 계산", "가격 예측", "재배 중 점검", "모델 검증", "수집 자료"]
    assert app.number_input(key="capex").value is None
    assert app.button(key="calculate").disabled
    assert any("실제 자료로 실행한 비교" in item.value for item in app.subheader)
    assert any("확보한 실제 자료" in item.value for item in app.subheader)


def test_completed_limix_results_appear_without_replacing_calculator_model():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    comparison = next(frame.value for frame in app.dataframe if "MAE (kg/10a)" in frame.value.columns)
    limix_rows = comparison.loc[comparison["모델"] == "LimiX-2 (400M)"]
    assert len(limix_rows) == 4
    assert limix_rows["지원 검증 행"].sum() == 100
    assert not limix_rows["선택"].any()
    assert any("3개 범위에서는 과거 중앙값" in item.value for item in app.info)
    predictions = next(frame.value for frame in app.dataframe if "limix_prediction" in frame.value.columns)
    assert len(predictions) == 108
    assert predictions["limix_prediction"].notna().sum() == 100


def test_explicit_test_quote_calculates_real_source_scenarios():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    # This amount is a test assumption, not a collected equipment quote.
    app.number_input(key="area").set_value(1000.0)
    app.number_input(key="capex").set_value(100_000_000).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    result = app.session_state["calculation_result"]
    payload = app.session_state["calculation_payload"]
    assert result["initial_capex_krw"] == 100_000_000
    assert result["area_m2"] == 1000
    assert payload["reference"]["year"] == 2024
    base = next(scenario for scenario in result["scenarios"] if scenario["name"] == "기준")
    assert base["cash_flows_krw"][0] == -100_000_000
    assert base["annual_revenue_krw"] == pytest.approx(payload["benchmark"]["yield_kg_per_1000m2"] * payload["benchmark"]["farmgate_price_krw_per_kg"])
    assert base["annual_cash_operating_cost_krw"] == pytest.approx(payload["benchmark"]["operating_cost_krw_per_1000m2"] - payload["benchmark"]["depreciation_krw_per_1000m2"])
    # Input changes must not leave a stale result visibly presented as current.
    app.number_input(key="area").set_value(2000.0).run()
    assert not app.exception
    assert any("입력이 변경" in item.value for item in app.info)


def test_retrofit_requires_baseline_and_experimental_model_runs():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="yield_mode").set_value("실험 모델").run()
    app.radio(key="mode").set_value("기존 시설 개량").run()
    app.number_input(key="capex").set_value(100_000_000).run()
    assert app.button(key="calculate").disabled
    app.number_input(key="baseline_cash").set_value(5_000_000).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    result = app.session_state["calculation_result"]
    assert result["mode"] == "retrofit"
    base = next(scenario for scenario in result["scenarios"] if scenario["name"] == "기준")
    assert base["annual_incremental_cash_flow_before_replacements_krw"] == pytest.approx(base["annual_cash_surplus_before_replacements_krw"] - 5_000_000)


def test_annual_rda_costs_cannot_be_multiplied_by_cycles_input():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not any(widget.key == "cycles" for widget in app.number_input)
    # A stale session from the earlier UI must not multiply annual depreciation.
    app.session_state["cycles"] = 6.0
    app.number_input(key="capex").set_value(100_000_000).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    payload = app.session_state["calculation_payload"]
    result = app.session_state["calculation_result"]
    base = next(scenario for scenario in result["scenarios"] if scenario["name"] == "기준")
    assert payload["cycles_per_year"] == 1
    assert result["cycles_per_year"] == 1
    assert base["annual_depreciation_krw"] == pytest.approx(payload["benchmark"]["depreciation_krw_per_1000m2"])
    assert base["annual_cash_operating_cost_krw"] == pytest.approx(payload["benchmark"]["operating_cost_krw_per_1000m2"] - payload["benchmark"]["depreciation_krw_per_1000m2"])


def test_market_prices_keep_variety_missingness_and_do_not_replace_farmgate_price():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.number_input(key="capex").set_value(100_000_000).run()
    app.button(key="calculate").click().run()
    farmgate_price = app.session_state["calculation_payload"]["benchmark"]["farmgate_price_krw_per_kg"]
    app.selectbox(key="kamis_crop").set_value("방울토마토").run()
    app.selectbox(key="kamis_variety").set_value("방울토마토").run()
    app.selectbox(key="kamis_grade").set_value("상품").run()
    assert not app.exception
    price_table = next(frame.value for frame in app.dataframe if "관측 상태" in frame.value.columns)
    assert len(price_table) == 60
    assert set(price_table["품종"]) == {"방울토마토"}
    assert price_table["가격 (원/kg)"].isna().sum() == 44
    assert price_table.loc[price_table["연월"] >= "2023-01", "가격 (원/kg)"].isna().all()
    assert app.session_state["calculation_payload"]["benchmark"]["farmgate_price_krw_per_kg"] == farmgate_price


def test_equipment_example_changes_capital_without_inventing_yield_gain():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="load_example").click().run()
    assert not app.exception
    app.button(key="calculate").click().run()
    before = app.session_state["calculation_payload"]
    assert before["initial_capex_krw"] == 112_530_300
    assert before["benchmark"]["yield_kg_per_1000m2"] == 3344.5
    app.number_input(key="equipment_qty_5126").set_value(2).run()
    assert any("입력이 변경" in item.value for item in app.info)
    app.button(key="calculate").click().run()
    after = app.session_state["calculation_payload"]
    assert after["initial_capex_krw"] == before["initial_capex_krw"] + 20_903_000
    assert after["benchmark"] == before["benchmark"]
    app.number_input(key="equipment_installation").set_value(None).run()
    assert app.button(key="calculate").disabled
    assert not app.exception


def test_market_and_weather_assumptions_change_scenario_not_source_benchmark():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="load_example").click().run()
    app.checkbox(key="use_market_transfer").check().run()
    app.radio(key="transfer_method").set_value("2024년에 선택한 모델").run()
    app.checkbox(key="use_weather_scenario").check().run()
    assert app.button(key="calculate").disabled
    app.number_input(key="weather_yield_change").set_value(-10.0)
    app.number_input(key="weather_cost_change").set_value(15.0).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    payload = app.session_state["calculation_payload"]
    base = app.session_state["calculation_result"]["scenarios"][1]
    assert payload["benchmark"]["yield_kg_per_1000m2"] == 3344.5
    assert payload["benchmark"]["farmgate_price_krw_per_kg"] == 10868
    assert base["annual_yield_kg"] == pytest.approx(3344.5 * .9)
    assert base["annual_cash_operating_cost_krw"] == pytest.approx((20_782_965 - 4_789_801) * 1.15)
    assert base["farmgate_price_krw_per_kg"] == pytest.approx(10868 * payload["reference_scenario"]["market"]["factor"])
    assert payload["reference_scenario"]["market"]["forecast_origin"] == "2025-12-31"
    assert payload["sensitivity_half_widths"]["yield"] == .1
    app.button(key="load_example").click().run()
    assert not app.checkbox(key="use_market_transfer").value
    assert not app.checkbox(key="use_weather_scenario").value
