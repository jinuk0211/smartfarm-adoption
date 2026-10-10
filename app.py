"""Local Streamlit prototype using collected data and explicit assumptions."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

from src.economics import evaluate_plan
from src.dashboard_ui import section, stat, takeaway
from src.dashboard_extensions import (
    apply_dashboard_style, render_equipment_selector, render_overview,
    render_price_forecast, render_risk_distribution,
    render_reference_scenarios,
    render_inseason_analysis,
)


PROJECT = Path(__file__).resolve().parent
DATA = PROJECT / "data" / "processed"


def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def won(value: float | None) -> str:
    return "산출 불가" if value is None else f"{value / 10000:,.1f}만원"


def completed_limix_result() -> dict | None:
    path = PROJECT / "artifacts" / "limix_metrics.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    current_metrics_hash = hashlib.sha256((PROJECT / "artifacts" / "model_metrics.json").read_bytes()).hexdigest()
    current_data_hash = hashlib.sha256((DATA / "rda_crop_income.csv").read_bytes()).hexdigest()
    if result.get("status") != "completed" or result.get("preprocessing_protocol") != "train_only_regression_v2" or result.get("original_metrics_sha256") != current_metrics_hash or result.get("source_csv_sha256") != current_data_hash:
        return None
    return result


def render_capex_reference(area: float) -> None:
    with st.expander("설치비 참고: 정부 사업계획 기준 단가"):
        reference = read_csv(str(DATA / "capex_reference.csv"))
        table = reference[["facility_type", "reference_krw_per_m2"]].copy()
        table["입력 면적 단순 환산액 (원)"] = table["reference_krw_per_m2"] * area
        st.dataframe(table.rename(columns={"facility_type": "시설 유형", "reference_krw_per_m2": "사업계획 기준 (원/㎡)"}), hide_index=True)
        st.caption("2026년 사업지침의 계획 예시이며 실제 견적·설치비·지원 확정액이 아닙니다. 사업 지원 규모는 3,000~20,000㎡이고, 위 환산액은 신청 자격을 뜻하지 않습니다.")
        st.write("제외 항목: 토지·부지조성·임차료·전기인입 200m 초과·냉난방 본체·농기계 등. 실제 견적에는 필요한 항목을 모두 포함하세요. 보조금은 자동 차감하지 않습니다.")
        st.markdown(f"[농림축산식품부 사업지침 출처]({reference.iloc[0]['source_page_url']})")


def render_results(result: dict, payload: dict) -> None:
    base = next(item for item in result["scenarios"] if item["name"] == "기준")
    section("계산 결과", "이 계획으로 얼마를 남길 수 있을까?", "입력한 조건을 유지할 때의 기준 시나리오입니다.")
    payback = base["payback_year"]
    columns = st.columns([1, 1.2, 1], gap="large")
    with columns[0]:
        stat("초기 투자금", won(result["initial_capex_krw"]), "선택한 설비와 추가 비용")
    with columns[1]:
        stat("자가노동까지 반영한 연 소득", won(base["annual_income_after_family_labor_krw"]), "감가상각·가족노동 기회비용 반영", emphasis=True)
    with columns[2]:
        stat("투자금 회수 시점", f"{payback}년 말" if payback is not None else "기간 내 미회수", "자가노동 기회비용 차감 전 현금흐름")
    st.caption("회수기간과 연 소득은 계산 기준이 다릅니다. 위 소득은 세후 순이익이 아니며, 개량 계획의 투자금 회수는 기존 유지 대비 추가 현금흐름으로 계산합니다.")
    if payback is not None and not base["recovered_by_horizon"]:
        st.warning("중간에 투자금을 회수했지만 이후 교체 지출 등으로 분석기간 말 잔액은 음수입니다.")
    table = []
    cumulative = {}
    annual = {}
    for scenario in result["scenarios"]:
        table.append({
            "시나리오": scenario["name"],
            "연간 수량 (kg)": round(scenario["annual_yield_kg"], 1),
            "연간 매출 (만원)": round(scenario["annual_revenue_krw"] / 10000, 1),
            "자가노동 반영 소득 (만원)": None if scenario["annual_income_after_family_labor_krw"] is None else round(scenario["annual_income_after_family_labor_krw"] / 10000, 1),
            "NPV (만원)": round(scenario["npv_krw"] / 10000, 1),
            "회수 시점": "기간 내 미회수" if scenario["payback_year"] is None else f"{scenario['payback_year']}년 말",
            "기간 내 회수 가능한 최대 투자비": won(scenario["maximum_capex_for_horizon_payback_krw"]),
        })
        cumulative[scenario["name"]] = [value / 10000 for value in scenario["cumulative_cash_flows_krw"]]
        annual[scenario["name"]] = [value / 10000 for value in scenario["cash_flows_krw"]]
    st.subheader("가격과 수확량이 달라지면, 회수 시점도 달라집니다")
    cumulative_frame = pd.DataFrame(cumulative).rename_axis("경과 연도")
    chart_data = cumulative_frame.reset_index().melt("경과 연도", var_name="조건", value_name="누적 현금흐름 (만원)")
    chart = alt.Chart(chart_data).mark_line(strokeWidth=3).encode(
        x=alt.X("경과 연도:Q", axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("누적 현금흐름 (만원):Q"),
        color=alt.Color("조건:N", scale=alt.Scale(domain=["불리", "기준", "유리"], range=["#b87640", "#1f593d", "#88a77b"]), legend=alt.Legend(orient="top")),
        tooltip=["조건:N", "경과 연도:Q", alt.Tooltip("누적 현금흐름 (만원):Q", format=",.0f")],
    )
    zero = alt.Chart(pd.DataFrame({"기준선": [0]})).mark_rule(color="#a8aea0", strokeDash=[4, 4]).encode(y="기준선:Q")
    st.altair_chart((chart + zero).properties(height=260).configure_view(stroke=None), width="stretch")
    st.caption("0선을 넘는 연말이 투자금을 회수하는 시점입니다. 불리: 출하량·가격 하락 / 현금비용 상승. 유리: 반대 방향.")
    with st.expander("연간 손익 · 시나리오별 수치 · 계산 기준"):
        columns = st.columns(3)
        columns[0].metric("연 매출", won(base["annual_revenue_krw"]))
        columns[1].metric("상각 반영 소득 · 자가노동 차감 전", won(base["annual_income_before_family_labor_krw"]))
        columns[2].metric("연간 투자 현금흐름", won(base["annual_incremental_cash_flow_before_replacements_krw"]))
        st.write(f"자가노동 기회비용은 연 **{won(base['annual_family_labor_opportunity_cost_krw'])}**입니다. 기준 순현재가치(NPV)는 **{won(base['npv_krw'])}**, {result['horizon_years']}년 말 누적 잔액은 **{won(base['undiscounted_balance_krw'])}**입니다.")
        st.caption("NPV는 할인율을 적용한 미래 현금흐름에서 초기 투자금을 뺀 값입니다. 소득에는 감가상각을 반영하지만, 현금흐름에서 다시 차감하지 않습니다.")
        required = base["required_annual_yield_for_horizon_payback_kg"]
        if required is not None:
            st.write(f"{result['horizon_years']}년 내 회수에 필요한 연간 출하량: **{required:,.0f}kg** · 현재 가정: **{base['annual_yield_kg']:,.0f}kg**")
            st.caption("할인 전 투자금 회수 기준입니다. 가족노동·세금·금융조달을 포함한 손익분기점은 아닙니다.")
        st.dataframe(pd.DataFrame(table), hide_index=True)
        annual_frame = pd.DataFrame(annual).rename_axis("경과 연도")
        st.write("연도별 현금흐름 (만원), 0년은 초기 투자")
        st.dataframe(annual_frame)
        st.write("누적 현금흐름 (만원)")
        st.dataframe(cumulative_frame)
        st.caption("신규는 전체 사업 현금흐름, 개량은 기존 유지 대비 추가 현금흐름입니다. 세금·금융조달·보조금·운전자금 증감·기말 처분가치는 제외했습니다.")
        st.download_button("입력 조건과 계산 결과 내려받기", json.dumps({"inputs": payload, "results": result}, ensure_ascii=False, indent=2), file_name="smartfarm_adoption_scenarios.json", mime="application/json", key="download_result")


def render_calculator(data: pd.DataFrame, metrics: dict) -> None:
    latest_year = int(data["year"].max())
    latest = data.loc[data["year"] == latest_year]
    intro_slot = st.container()
    result_slot = st.container()
    with st.expander("01  재배 계획 · 품목, 면적, 수량 기준", expanded=not st.session_state.get("example_loaded", False)):
        columns = st.columns(3)
        crop = columns[0].selectbox("품목", sorted(latest["crop"].unique()), key="crop")
        crop_data = latest.loc[latest["crop"] == crop]
        category = columns[1].selectbox("원문 재배 분류", sorted(crop_data["crop_original"].unique()), key="category")
        category_data = crop_data.loc[crop_data["crop_original"] == category]
        regions = sorted(category_data["region"].unique(), key=lambda item: (item != "전국", item))
        region = columns[2].selectbox("기준 지역", regions, key="region")
        row = category_data.loc[category_data["region"] == region].iloc[0]
        st.caption(f"기준: {latest_year}년 · {row['crop_original']} · {region} · {row['period_basis']}. 지역 자료는 조사 사례이며 지역 전체의 대표값으로 보장되지 않습니다.")
        columns = st.columns(3)
        area = columns[0].number_input("계획 재배면적 (㎡)", min_value=1.0, value=1000.0, step=100.0, key="area")
        planned_year = columns[1].number_input("예정 재배연도", min_value=latest_year + 1, value=max(date.today().year, latest_year + 1), step=1, key="planned_year")
        cycles = 1.0
        columns[2].metric("계산 기간 기준", "연간 1기작")
        yield_mode = st.radio("수량 기준", ["최신 실측 집계", "실험 모델"], horizontal=True, key="yield_mode")
        yield_value = float(row["yield_kg_per_1000m2"])
        prediction = None
        if yield_mode == "실험 모델":
            from src.smartfarm_model import predict_yield

            scope = "national" if region == "전국" else "regional"
            group = next((group for group in metrics["groups"] if group["geographic_scope"] == scope and group["classification_regime"] == row["schema_regime"] and group["period_basis"] == row["period_basis"]), None)
            if group and group["artifact_files"].get("bundle"):
                bundle_path = PROJECT / "artifacts" / Path(group["artifact_files"]["bundle"]).name
                prediction = predict_yield(bundle_path, {"year": int(planned_year), "crop": crop, "cultivation_type": row["cultivation_type"], "region": region, "source_category": category})
            yield_value = None if prediction is None else prediction["yield_kg_per_1000m2"]
            if yield_value is None:
                st.info("선택 조건을 지원하는 모델 자료가 없습니다. 최신 실측 집계를 선택해 계산할 수 있습니다.")
            else:
                st.caption(f"선택된 방법: {prediction['model']} · 같은 조건 참고 행 {prediction['n_reference_rows']}개 · 최신 관측 {prediction['latest_source_year']}년. 비교 실험에서는 과거 중앙값이 CatBoost·XGBoost보다 오차가 작았습니다.")
        if yield_value is not None:
            st.write(f"수량 기준 **{yield_value:,.1f} kg / 1,000㎡ / 년(1기작)** · 농가수취단가 **{row['farmgate_price_krw_per_kg']:,.0f} 원/kg**")
        st.caption("원자료가 연간 1기작 기준이므로 연간 횟수는 1로 고정합니다. 수량·비용·감가상각은 면적만 환산합니다. 예정연도에 따른 가격·비용 상승률을 자동 예측하지 않으며 선택한 연간 조건이 분석기간 동안 유지된다고 가정합니다.")

    with st.expander("02  투자 계획 · 설비와 비용", expanded=not st.session_state.get("example_loaded", False)):
        mode_label = st.radio("사업 구분", ["신규 도입", "기존 시설 개량"], horizontal=True, key="mode")
        mode = "new" if mode_label == "신규 도입" else "retrofit"
        cost_source = st.radio("투자비 산정 방법", ["직접 견적·가정 입력", "장비 구성으로 계산"], horizontal=True, key="capex_source")
        equipment_provenance = None
        if cost_source == "장비 구성으로 계산":
            capital, equipment_provenance = render_equipment_selector(PROJECT)
        columns = st.columns(3)
        if cost_source == "직접 견적·가정 입력":
            capital = columns[0].number_input("설치·개량 투자비 (원) · 필수", min_value=0, value=None, step=1000000, placeholder="견적 또는 명시적 가정 입력", key="capex")
        else:
            columns[0].metric("선택 구성의 초기 투자비", won(capital))
        horizon = columns[1].number_input("분석기간 (년)", min_value=1, max_value=30, value=10, step=1, key="horizon")
        discount = columns[2].number_input("연 할인율 (%)", min_value=0.0, max_value=30.0, value=4.0, step=0.5, key="discount")
        st.caption("신규는 사업에 필요한 전체 투자비, 개량은 기존 시설 유지 대비 추가 투자비를 입력하세요. 견적·가정의 출처는 다운로드 결과와 함께 별도로 보관하세요.")
        baseline_cash = None
        if mode == "retrofit":
            baseline_cash = st.number_input("기존 유지 시 연간 현금흐름 (원) · 필수", value=None, step=1000000, placeholder="매출 − 현금 운영비, 교체비 차감 전", key="baseline_cash")
        render_capex_reference(area)
    reference_scenario, references_ready = render_reference_scenarios(PROJECT, crop, int(planned_year))

    with st.expander("03  변화에 대비하기 · 출하량, 가격, 비용, 교체"):
        columns = st.columns(3)
        yield_change = columns[0].number_input("출하량 변동 폭 (±%)", min_value=0.0, max_value=90.0, value=10.0, step=5.0, key="yield_change") / 100
        price_change = columns[1].number_input("가격 변동 폭 (±%)", min_value=0.0, max_value=90.0, value=20.0, step=5.0, key="price_change") / 100
        cost_change = columns[2].number_input("현금 운영비 변동 폭 (±%)", min_value=0.0, max_value=90.0, value=10.0, step=5.0, key="cost_change") / 100
        st.caption("불리: 출하·가격 감소, 현금비용 증가 / 유리: 반대 방향. 사용자가 정하는 가정이며 신뢰구간·손실확률·장비 효과 추정치가 아닙니다.")
        has_replacement = st.checkbox("분석기간 중 교체 투자 반영", key="has_replacement")
        replacement_year = None
        replacement_cost = None
        baseline_replacement_cost = None
        if has_replacement:
            columns = st.columns(2)
            replacement_year = columns[0].number_input("교체 연도 (도입 후)", min_value=1, max_value=int(horizon), value=min(5, int(horizon)), step=1, key="replacement_year")
            replacement_cost = columns[1].number_input("도입안 교체비 (원)", min_value=0, value=None, step=1000000, key="replacement_cost")
            if mode == "retrofit":
                baseline_replacement_cost = st.number_input("같은 연도 기존 유지안 교체비 (원) · 없으면 0 명시", min_value=0, value=None, step=1000000, key="baseline_replacement_cost")

    ready = capital is not None and yield_value is not None and references_ready
    if mode == "retrofit":
        ready = ready and baseline_cash is not None
    if has_replacement:
        ready = ready and replacement_cost is not None and (mode != "retrofit" or baseline_replacement_cost is not None)
    if not ready:
        st.info("설치비와 선택한 계획의 필수 금액을 입력하면 계산할 수 있습니다. 모델 검증·수집 자료 탭은 바로 확인할 수 있습니다.")
    if ready:
        st.write(f"**{crop} · {region} · {area:,.0f}㎡**　|　초기 투자 {won(capital)}　|　{int(horizon)}년 비교")
    clicked = st.button("시나리오 계산", type="primary", disabled=not ready, key="calculate")
    if not ready or (not clicked and "calculation_result" not in st.session_state):
        with intro_slot:
            section("나의 도입 계획", "재배와 투자 조건을 정해보세요", "금액을 모르는 항목은 비워 두세요. 확인한 금액이 모두 있어야 계산할 수 있습니다.")
    if not ready:
        return
    fields = ["farmgate_price_krw_per_kg", "operating_cost_krw_per_1000m2", "depreciation_krw_per_1000m2", "family_labor_cost_krw_per_1000m2"]
    benchmark = {field: None if pd.isna(row[field]) else float(row[field]) for field in fields}
    benchmark.update(yield_kg_per_1000m2=yield_value, period_basis=row["period_basis"])
    payload = {
        "benchmark": benchmark, "area_m2": area, "cycles_per_year": cycles,
        "initial_capex_krw": capital, "horizon_years": int(horizon), "discount_rate": discount / 100, "mode": mode,
        "replacements_krw": {} if not has_replacement else {str(replacement_year): replacement_cost},
        "scenarios": [
            {"name": "불리", "yield_multiplier": reference_scenario["yield_multiplier"] * (1 - yield_change), "price_multiplier": reference_scenario["price_multiplier"] * (1 - price_change), "cash_cost_multiplier": reference_scenario["cash_cost_multiplier"] * (1 + cost_change)},
            {"name": "기준", "yield_multiplier": reference_scenario["yield_multiplier"], "price_multiplier": reference_scenario["price_multiplier"], "cash_cost_multiplier": reference_scenario["cash_cost_multiplier"]},
            {"name": "유리", "yield_multiplier": reference_scenario["yield_multiplier"] * (1 + yield_change), "price_multiplier": reference_scenario["price_multiplier"] * (1 + price_change), "cash_cost_multiplier": reference_scenario["cash_cost_multiplier"] * (1 - cost_change)},
        ],
        "reference": {"crop": crop, "source_category": category, "region": region, "year": latest_year, "planned_year": int(planned_year), "source_url": row["source_url"], "source_page": int(row["source_page"]), "yield_mode": yield_mode, "model_prediction": prediction},
        "capital_cost_basis": equipment_provenance or {"type": "user_entered_quote_or_assumption"},
        "reference_scenario": reference_scenario,
        "sensitivity_half_widths": {"yield": yield_change, "price": price_change, "cash_cost": cost_change},
    }
    if mode == "retrofit":
        payload["baseline"] = {"annual_cash_flow_krw": baseline_cash, "replacements_krw": {} if not has_replacement else {str(replacement_year): baseline_replacement_cost}}
    if clicked:
        st.session_state["calculation_result"] = evaluate_plan(payload)
        st.session_state["calculation_payload"] = payload
    if "calculation_result" in st.session_state:
        if st.session_state["calculation_payload"] == payload:
            with result_slot:
                render_results(st.session_state["calculation_result"], payload)
                with st.expander("더 다양한 조건으로 비교하기 · 2,000가지 가정"):
                    render_risk_distribution(payload)
                st.subheader("계획 바꾸기")
        else:
            with result_slot:
                st.info("입력이 변경되었습니다. 시나리오 계산을 다시 누르면 새 조건의 결과를 표시합니다.")
    with st.expander("계산에 사용하는 자료와 한계"):
        st.write("수량·비용은 지역·품목의 조사 집계자료입니다. 장비 설치에 따른 수확량 증가나 개별 신규 농가의 수익률을 검증한 모델은 아닙니다.")
        st.caption("상각비와 자가노동비는 선택한 소득조사의 연간 기준값입니다. 입력한 설치 견적에서 새로 계산한 상각비가 아니며, 면적만 환산했습니다.")


def render_validation(metrics: dict) -> None:
    st.subheader("실제 자료로 실행한 비교")
    st.write("과거 중앙값·직전 연도값·CatBoost·XGBoost를 비교했습니다. 가장 최근 관측연도를 검증용으로 남겼고, 전국/지역 자료 및 2023년 조사 분류 변경 전후를 분리했습니다.")
    rows = []
    for group in metrics["groups"]:
        for name, metric in group["metrics"].items():
            rows.append({"범위": "전국" if group["geographic_scope"] == "national" else "지역", "분류 시기": group["classification_regime"], "검증연도": group["holdout_year"], "학습 행": group["n_train"], "지원 검증 행": metric["n_scored"], "모델": name, "MAE (kg/10a)": metric["mae_kg_per_1000m2"], "RMSE (kg/10a)": metric["rmse_kg_per_1000m2"], "선택": name == group.get("selected_on_holdout")})
    limix = completed_limix_result()
    if limix:
        original_groups = {group["group_id"]: group for group in metrics["groups"]}
        for metric in limix["groups"]:
            group = original_groups[metric["group_id"]]
            rows.append({"범위": "전국" if group["geographic_scope"] == "national" else "지역", "분류 시기": group["classification_regime"], "검증연도": metric["holdout_year"], "학습 행": metric["n_train"], "지원 검증 행": metric["n_scored"], "모델": "LimiX-2 (400M)", "MAE (kg/10a)": metric["mae_kg_per_1000m2"], "RMSE (kg/10a)": metric["rmse_kg_per_1000m2"], "선택": False})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("전국 자료는 표본이 적어 CatBoost·XGBoost 학습에서 제외했습니다. LimiX 완료 결과가 있으면 과거값과 함께 표시합니다. 같은 검증자료로 후보를 선택했으므로 독립적인 최종 성능검증이 아닙니다. 이 결과는 개별 농가·장비 설치효과의 정확도를 입증하지 않습니다. 학습에 없던 조건은 성능 평가에서 제외했습니다.")
    predictions_name = "limix_holdout_predictions.csv" if limix else "holdout_predictions.csv"
    predictions = read_csv(str(PROJECT / "artifacts" / predictions_name))
    with st.expander("실제 검증 관측값·예측값"):
        st.dataframe(predictions, hide_index=True)
    st.download_button("검증 예측 CSV 다운로드", predictions.to_csv(index=False).encode("utf-8-sig"), file_name=predictions_name, mime="text/csv", key="download_predictions")
    if limix:
        baseline_better = sum(metric["baseline_mae"] < metric["mae_kg_per_1000m2"] for metric in limix["groups"])
        st.info(f"LimiX-2의 4억 파라미터 모델을 {len(limix['groups'])}개 범위의 같은 검증 행으로 실행했습니다. 이 중 {baseline_better}개 범위에서는 과거 중앙값의 MAE가 더 작았습니다.")
        st.caption("Built with StableAI LimiX · 비상업 연구용 실행 · Windows의 PyTorch RMSNorm 호환 설정 사용. 이 비교는 개별 농가 예측 성능이나 장비 도입효과를 검증한 결과가 아닙니다.")
    else:
        st.info("현재 데이터와 비교 조건에 맞는 LimiX-2 완료 결과가 없습니다. 현재 모델은 RDA 공개 집계자료로 만든 초기 비교 실험입니다.")
    render_adp_timing_validation()
    render_curation_validation()


def render_curation_validation() -> None:
    names = {"global_median": "총량 중앙값", "month_median": "정식월 중앙값",
             "area_scaled_median": "면적당 중앙값 기준선", "crop_median": "품목 중앙값",
             "crop_month_median": "품목·정식월 중앙값", "catboost": "CatBoost",
             "xgboost": "XGBoost", "limix_2_400m": "LimiX-2 (400M)"}
    for prefix, title, target, unit, metric in [
        ("strawberry_curation", "딸기: 기록된 작기 총출하량", "reported_cycle_total_kg", "kg", "kg"),
        ("regional_curation", "5품목: 기록된 작기 총매출", "revenue_krw_per_cycle", "원", "krw"),
    ]:
        path = PROJECT / "artifacts" / f"{prefix}_metrics.json"
        if not path.exists():
            continue
        try:
            result = json.loads(path.read_bytes())
            if result.get("status") != "completed" or result.get("target") != target:
                continue
            hashes = result.get("input_sha256", {})
            if not hashes or any(hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() != value for name, value in hashes.items()):
                continue
            if result.get("limix", {}).get("preprocessing_protocol") != "train_only_regression_v2":
                continue
            stages = result.get("stages", {})
            if any(stages.get(stage, {}).get("status") != "completed" for stage in ["classical", "limix"]):
                continue
            code_current = True
            for stage in ["classical", "limix"]:
                code_hashes = stages[stage].get("source_sha256", {})
                if not code_hashes or any(hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() != value for name, value in code_hashes.items()):
                    code_current = False
                    break
            if not code_current or set(result.get("studies", {})) != {"primary_recorded", "sensitivity_without_flagged_extreme"}:
                continue
            predictions = {}
            for study, record in result["studies"].items():
                content = (PROJECT / "artifacts" / f"{prefix}_{study}_oof.csv").read_bytes()
                if hashlib.sha256(content).hexdigest() != record["oof_sha256"]:
                    break
                predictions[study] = content
            if set(predictions) != set(result["studies"]):
                continue
        except (OSError, ValueError, KeyError):
            continue
        st.subheader(title)
        st.write("동일 시설의 작기를 학습·검증에 나누지 않은 5분할 비교입니다. 주 결과에는 원자료의 극단값도 포함했습니다.")
        labels = {"primary_recorded": "주 결과 · 극단값 포함",
                  "sensitivity_without_flagged_extreme": "민감도 · 검토 대상 극단값 제외"}
        rows = []
        for study, record in result["studies"].items():
            for name, score in record["models"].items():
                rows.append({"평가 범위": labels.get(study, study), "모델": names.get(name, name),
                             "평가 작기": score["n_scored"], f"MAE ({unit}/작기)": score[f"mae_{metric}"],
                             f"RMSE ({unit}/작기)": score[f"rmse_{metric}"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("민감도 결과는 같은 시설별 분할에서 표시한 극단값만 제외하고 다시 학습한 결과입니다. 원기록이 오류라는 확정이나 독립적인 최종 검증은 아닙니다. 결측·의미 미확정 0값을 제외한 표본이라 신규 농가 전체의 성과·실패확률을 나타내지 않습니다.")
        if prefix == "strawberry_curation":
            st.caption("관측 품종은 설향입니다. 면적은 시설·품목·작기 기간이 정확히 연결된 API의 ㎡ 값만 사용했습니다. 총kg를 면적당 연간 수량으로 자동 환산하지 않았습니다.")
        else:
            st.caption("매출은 순이익이 아닙니다. 정의서의 평 단위와 API 면적 수치가 충돌해 이 모델의 입력에서 면적을 제외했습니다.")
        st.caption("Built with StableAI LimiX · 비상업 연구용 비교. 생육·환경·출하 등급 등 재배 후 결과를 사전 입력으로 사용하지 않았으며 경제성 계산에 자동 연결하지 않았습니다.")
        for study, content in predictions.items():
            st.download_button(f"{title} — {labels.get(study, study)} CSV", content,
                               file_name=f"{prefix}_{study}_oof.csv", mime="text/csv", key=f"download_{prefix}_{study}")


def render_adp_timing_validation() -> None:
    path = PROJECT / "artifacts" / "adp_timing_metrics.json"
    if not path.exists():
        return
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "completed" or result.get("target") != "days_to_first_recorded_shipment":
        return
    expected_files = {"adp_cultivation_cycles.csv", "adp_cycle_quality.csv"}
    hashes = result.get("input_sha256", {})
    if set(hashes) != expected_files or any(hashlib.sha256((DATA / name).read_bytes()).hexdigest() != value for name, value in hashes.items()):
        return
    if result.get("limix", {}).get("preprocessing_protocol") != "train_only_regression_v2":
        return
    predictions_path = PROJECT / "artifacts" / "adp_timing_oof_predictions.csv"
    if not predictions_path.exists():
        return
    predictions = predictions_path.read_bytes()
    if hashlib.sha256(predictions).hexdigest() != result.get("oof_sha256"):
        return
    st.subheader("농가 원자료: 첫 출하 기록 시점 비교 실험")
    audit = result["data_audit"]
    st.write(f"ADP {audit['n_included']}개 작기를 지역·농가코드 기준 {audit['n_farm_groups']}개 그룹으로 묶어 5개 검증 분할로 비교했습니다. 정식일부터 첫 번째 기록된 출하일까지의 일수를 예측했습니다.")
    st.caption("기록 시작일이 실제 첫 수확일이라는 보장은 없습니다. 이 실험은 생산량·수익 예측이 아니며 경제성 계산에 연결하지 않습니다. 실제 농가 식별체계와 관측 시작 시점의 추가 검증이 필요합니다.")
    rows, crop_rows = [], []
    names = {"crop_median": "품목별 중앙값", "crop_month_median": "품목·정식월 중앙값", "catboost": "CatBoost", "xgboost": "XGBoost", "limix_2_400m": "LimiX-2 (400M)"}
    for name, metric in result["models"].items():
        rows.append({"모델": names.get(name, name), "평가 작기": metric["n_scored"], "MAE (일)": metric["mae_days"], "RMSE (일)": metric["rmse_days"]})
        for crop, item in metric["by_crop"].items():
            crop_rows.append({"품목": crop, "모델": names.get(name, name), "평가 작기": item["n_scored"], "MAE (일)": item["mae_days"], "RMSE (일)": item["rmse_days"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    with st.expander("농가 기록 시점의 품목별 결과"):
        st.dataframe(pd.DataFrame(crop_rows), hide_index=True)
    st.caption("생산 기록이 없는 작기를 0일로 바꾸지 않았습니다. 출하·생육·환경 관측값, 생산기록 건수와 마지막 출하일을 입력으로 쓰지 않았습니다. 이 교차검증은 모델 비교용이며 별도의 최종 평가자료 검증은 아닙니다.")
    st.download_button("농가 기록 시점 검증 CSV 다운로드", predictions, file_name="adp_timing_oof_predictions.csv", mime="text/csv", key="download_adp_timing_predictions")


def render_market_reference() -> None:
    st.subheader("KAMIS 월별 시장가격 참고")
    prices = read_csv(str(DATA / "kamis_wholesale_monthly_kg.csv"))
    observed_count = int(prices["price_krw_per_kg"].notna().sum())
    st.write(f"2021~2025년 실제 1kg 단위의 월·품종·등급 격자 {len(prices):,}행, 관측 가격 {observed_count:,}개, 결측 {len(prices) - observed_count:,}개를 보존했습니다.")
    st.caption("중도매인 판매가격입니다. 농가수취단가가 아니며 도입 전 계산의 매출·단가에 대입하지 않습니다. 품종·등급별로 따로 조회하며 결측을 다른 품종이나 0원으로 채우지 않습니다. 50개 단위로 제공된 오이 품종은 kg 표에서 제외했습니다.")
    columns = st.columns(3)
    crop = columns[0].selectbox("시장가격 품목", sorted(prices["crop"].unique()), key="kamis_crop")
    crop_prices = prices.loc[prices["crop"] == crop]
    variety = columns[1].selectbox("시장가격 품종", sorted(crop_prices["variety"].unique()), key="kamis_variety")
    variety_prices = crop_prices.loc[crop_prices["variety"] == variety]
    grade = columns[2].selectbox("시장가격 등급", sorted(variety_prices["grade"].unique()), key="kamis_grade")
    selected = variety_prices.loc[variety_prices["grade"] == grade].sort_values("year_month")
    chart = pd.DataFrame({"연월": pd.to_datetime(selected["year_month"]), "중도매인 판매가격 (원/kg)": selected["price_krw_per_kg"]})
    st.scatter_chart(chart, x="연월", y="중도매인 판매가격 (원/kg)")
    st.caption("점은 실제 관측 가격입니다. 관측이 없는 월은 점을 표시하지 않으며 아래 표에 결측 상태를 남겼습니다.")
    table = selected[["crop", "variety", "grade", "year_month", "price_krw_per_kg", "observation_status"]].rename(columns={"crop": "품목", "variety": "품종", "grade": "등급", "year_month": "연월", "price_krw_per_kg": "가격 (원/kg)", "observation_status": "관측 상태"}).copy()
    table["관측 상태"] = table["관측 상태"].replace({"observed": "관측값", "source_dash": "원문 대시 · 결측", "month_row_not_listed": "원문 월 행 미제공 · 결측"})
    st.dataframe(table, hide_index=True)
    st.markdown(f"[선택 조건의 KAMIS 원문 가격표]({selected.iloc[0]['source_url']})")


def render_smartfarm_api_sources() -> str:
    st.subheader("스마트팜코리아 작기별 원자료")
    manifests = sorted((PROJECT / "data" / "raw" / "smartfarm_api").glob("*/manifest.json"), reverse=True)
    if not manifests:
        st.info("저장된 API 수집 자료가 없습니다.")
        return "저장된 API 원자료 없음"
    if st.button("API 수집 현황 새로고침", key="refresh_api_sources"):
        st.rerun()
    manifest_path = manifests[0]
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        st.info("수집 기록을 갱신 중입니다. 잠시 후 현황을 새로고침하세요.")
        return "수집 기록 갱신 중"
    state = manifest.get("status")
    labels = {"in_progress": "수집 중", "completed": "선택 범위 조회 완료", "catalog_only": "목록만 확보", "truncated": "일부 범위만 수집", "completed_with_skips": "일부 작기 제외", "failed": "수집 중 오류", "no_matching_catalog_records": "조건에 맞는 목록 없음"}
    state_label = labels.get(state, "수집 상태 확인 필요")
    st.write(f"**{state_label}** · 목록의 시설 {manifest.get('catalog', {}).get('facility_count', 0):,}개")
    operations = {"getFcltyInfoDataList": "시설·작기 목록", "getFcltyDateInfoData": "작기 기간·품목", "getMngtOutputDataList": "출하·판매수입", "getMngtCostDataList": "비용 기록"}
    rows = []
    for operation, label in operations.items():
        requests = [item for item in manifest.get("requests", []) if item["source_operation"] == operation]
        saved = [item for item in requests if item.get("status") == "saved"]
        rows.append({"자료": label, "저장 행": sum(item.get("record_count") or 0 for item in saved), "저장 응답": len(saved), "자료 없음 응답": sum(bool(item.get("no_data")) for item in saved), "실패 응답": sum(item.get("status") == "failed" for item in requests)})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("동일 실행의 저장 결과입니다. 자료 없음 응답은 0수확량·0비용 관측이 아닙니다. 아직 조회하지 않은 작기의 자료 유무도 판단할 수 없습니다. 목록 행 수와 독립 농가 수는 다릅니다.")
    if state != "completed":
        st.info("현재는 일부 자료입니다. 이 건수를 전체 확보량이나 학습 표본 수로 사용하지 않습니다.")
    audit_path = DATA / "smartfarm_api_audit.json"
    if audit_path.exists():
        try:
            audit_bytes = audit_path.read_bytes()
            audit = json.loads(audit_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError):
            audit = None
        if audit and audit.get("source_run_id") == manifest_path.parent.name and audit.get("source_manifest_sha256") == hashlib.sha256(manifest_bytes).hexdigest():
            st.write("원자료 연결·품질 검사를 마쳤습니다. 조회 범위 확인: " + ("완료" if audit.get("request_scope_complete") else "미완료"))
            st.download_button("API 자료 품질 검사표 다운로드", audit_bytes, file_name="smartfarm_api_audit.json", mime="application/json", key="download_api_audit")
    st.write("명세에서 면적(㎡), 출하량(kg), 수입·비용(원)은 확인했습니다. 기록별 집계기간·누적 여부, 작기 자료의 완결성, 비용 항목 간 중복은 확인이 남아 있습니다.")
    st.caption("API 예측모델은 아직 실행하지 않았고 경제성 계산에도 연결하지 않았습니다. 현재 계산기는 농촌진흥청 소득조사 기준을 사용합니다.")
    st.caption(f"수집 실행: {manifest_path.parent.name} · 시작: {manifest.get('started_at_utc', '')}")
    return f"{state_label} · 수량·비용 집계 정의 검증 필요"


def render_sources(data: pd.DataFrame) -> None:
    st.subheader("확보한 실제 자료")
    columns = st.columns(3)
    columns[0].metric("소득조사 관측 행", f"{len(data):,}")
    columns[1].metric("소득조사 원본 PDF", len(list((PROJECT / "data" / "raw" / "rda").glob("*.pdf"))))
    columns[2].metric("관측 연도", f"{int(data.year.min())}–{int(data.year.max())}")
    counts = data.groupby(["year", "source_scope"]).size().reset_index(name="관측 행")
    st.dataframe(counts.rename(columns={"year": "연도", "source_scope": "집계 범위"}), hide_index=True)
    st.write("농사로 소득자료집의 집계표를 수집했습니다. 가격은 농가수취단가이고, 수량·비용은 10a(1,000㎡)·연간 1기작 기준입니다. 원문 파일·쪽수·출처 URL·해시를 함께 보존했습니다.")
    with st.expander("수집 행과 원문 출처"):
        st.dataframe(data, hide_index=True)
    st.download_button("수집 집계자료 CSV 다운로드", data.to_csv(index=False).encode("utf-8-sig"), file_name="rda_crop_income.csv", mime="text/csv", key="download_data")
    reference_path = DATA / "smartfarm_yield_reference_groups.csv"
    if reference_path.exists():
        reference = read_csv(str(reference_path))
        st.write(f"스마트팜 공개 생산량 참고 집계 {len(reference)}행도 별도 확보했습니다. 농가별 원자료가 아니므로 현재 학습에는 넣지 않았습니다.")
    st.caption("농사로 자료집은 출처 표시·비상업 조건(공공누리 제2유형)으로 안내됩니다. 정부 설치비 기준은 별도 사업계획 참고자료이며 실제 견적이 아닙니다.")
    render_market_reference()
    climate_path = DATA / "climate_normals_monthly.csv"
    if climate_path.exists():
        st.subheader("기상청 월별 기후평년값")
        climate = read_csv(str(climate_path))
        stations = climate[["station_id", "station_name"]].drop_duplicates().set_index("station_id")["station_name"].to_dict()
        station_id = st.selectbox("기후 관측지점", list(stations), format_func=lambda value: f"{stations[value]} ({value})", key="climate_station")
        selected_climate = climate.loc[climate["station_id"] == station_id].sort_values("month")
        st.caption(f"1991~2020 기준 평년값 · {len(stations)}개 지점 · {len(climate):,}개 지점·월. 해당 지점의 장기 기후 참고값이며 예정 작기의 실제 날씨 예측은 아닙니다. 농가 위치와 임의로 연결하거나 기존 모델 입력으로 사용하지 않았습니다.")
        climate_table = selected_climate[["month", "mean_temperature_c", "mean_max_temperature_c", "mean_min_temperature_c", "monthly_precipitation_mm"]].rename(columns={"month": "월", "mean_temperature_c": "평균기온 (℃)", "mean_max_temperature_c": "평균최고기온 (℃)", "mean_min_temperature_c": "평균최저기온 (℃)", "monthly_precipitation_mm": "강수량 (mm)"})
        st.line_chart(climate_table, x="월", y=["평균기온 (℃)", "평균최고기온 (℃)", "평균최저기온 (℃)"])
        st.dataframe(climate_table, hide_index=True)
        st.markdown("[기상청 기후평년값 안내](https://data.kma.go.kr/normals/info1.do)")
    adp_quality_path = DATA / "adp_cycle_quality.csv"
    if adp_quality_path.exists():
        adp_quality = read_csv(str(adp_quality_path))
        st.subheader("ADP 스마트팜 농가 원자료")
        st.write(f"재배정보 {len(adp_quality):,}건에 생산기록 {int(adp_quality['production_record_count'].sum()):,}행을 연결했습니다. 재배정보는 농가·작기별 행이며 독립 농가 수와 다릅니다.")
        adp_counts = adp_quality.assign(has_records=adp_quality["production_record_count"] > 0).groupby("crop", as_index=False).agg(재배정보=("cycle_id", "size"), 생산기록있는작기=("has_records", "sum"), 생산기록행=("production_record_count", "sum"))
        st.dataframe(adp_counts.rename(columns={"crop": "원문 품목"}), hide_index=True)
        st.caption("출하량·면적 단위와 기록별 집계기간이 원본에 명시되지 않아 kg/㎡ 생산량 및 경제성 계산에 연결하지 않았습니다. 같은 날짜의 여러 출하행과 원본 동일행을 임의로 제거하거나 합산하지 않았습니다.")
        st.download_button("작기별 자료 품질표 다운로드", adp_quality.to_csv(index=False).encode("utf-8-sig"), file_name="adp_cycle_quality.csv", mime="text/csv", key="download_adp_quality")
        st.markdown("[농촌진흥청 ADP 원자료 안내](https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE)")
    api_status = render_smartfarm_api_sources()
    render_curation_sources()
    render_dsz_preparation()
    farm_cases_path = DATA / "public_farm_gg2023_cases.csv"
    if farm_cases_path.exists():
        st.subheader("공식 보고서의 개별 농가 사례")
        farm_cases = read_csv(str(farm_cases_path))
        st.write(f"경기도 2023년 기술보급 보고서의 개별 농가 사례 {len(farm_cases)}건을 확보했습니다. 수량 단위와 작기 기간이 불명확해 예측 모델 학습에는 사용하지 않았습니다.")
        st.dataframe(farm_cases[["case_id", "city", "crop_facility_table", "crop_income_table", "intervention", "pilot_area_m2"]].rename(columns={"case_id": "출처 행 ID", "city": "시군", "crop_facility_table": "시설표 품목", "crop_income_table": "소득표 품목", "intervention": "시범사업 유형", "pilot_area_m2": "시범 면적 (㎡)"}), hide_index=True)
        st.caption("농가 이름을 제외하고 출처 행으로 관리합니다. 두 표의 품목명이 다른 경우 원문을 유지했습니다. 보고서의 기술보급 사업비는 전체 농가 설치 견적과 구분합니다.")
        st.markdown(f"[경기도농업기술원 원문 보고서]({farm_cases.iloc[0]['source_url']})")
    st.subheader("추가 확인·확보가 필요한 항목")
    st.dataframe(pd.DataFrame([
        {"항목": "ADP 출하량·면적 및 집계기간 정의", "상태": "원자료 확보·연결 완료, 생산량 타깃 정의 확인 필요"},
        {"항목": "스마트팜 API", "상태": api_status},
        {"항목": "대회 미개방 시설·경영 원자료", "상태": "대구 방문 완료(사용자 확인) · 현장에서 실제 파일로 실행"},
        {"항목": "설비별 가격과 현장 견적", "상태": "공개 등록가격 3종 연결 완료 · 현장 공사비·부가세·호환성은 별도 확인"},
    ]), hide_index=True)


def render_dsz_preparation() -> None:
    st.subheader("안심구역: 명세서 기반 현장 실행")
    st.write("시설·경영조사 파일을 넣으면 검사·연결·출하량 및 매출 모델 비교·저장·계획 예측을 실행합니다. 사용자는 대구센터 방문을 완료했으며, 실제 미개방 자료는 현장에서 사용합니다.")
    st.caption("동봉 예제는 합성 자료입니다. 예제의 점수·예측은 실제 농가 성능이나 대회 데이터 활용 실적을 뜻하지 않습니다. 경영 기록의 증분·누계·작기 총량 해석은 실행 옵션에 기록합니다.")
    st.code('.\\run_dsz.ps1 -Demo\n.\\run_dsz.ps1 -InputDir D:\\approved_data -Plans D:\\plans.csv', language="powershell")
    guide = PROJECT / "reports" / "dsz_onsite_guide.md"
    if guide.exists():
        st.download_button("현장 실행 안내 다운로드", guide.read_bytes(), file_name=guide.name,
                           mime="text/markdown", key="download_dsz_guide")
    proof_path = PROJECT / "artifacts" / "dsz_verification.json"
    if not proof_path.exists():
        return
    try:
        proof = json.loads(proof_path.read_bytes())
        if proof.get("status") != "passed" or proof.get("data_kind") != "synthetic_schema_fixture":
            return
        hashes = proof.get("verified_files", {})
        if not hashes or any(hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() != value for name, value in hashes.items()):
            return
        archive = PROJECT / proof["source_bundle"]
        archive.resolve().relative_to((PROJECT / "artifacts" / "dsz_packages").resolve())
        content = archive.read_bytes()
        if hashlib.sha256(content).hexdigest() != proof["source_bundle_sha256"]:
            return
    except (OSError, ValueError, KeyError):
        return
    st.info("합성 예제의 전처리 → 모델 비교 → 저장 → 예측을 검증했습니다. Windows x64 · Python 3.12 새 환경에서 동봉 패키지만으로 설치·실행했습니다.")
    st.download_button("현장 실행 코드 ZIP 다운로드", content, file_name=archive.name,
                       mime="application/zip", key="download_dsz_source")
    st.caption("이 작은 ZIP은 코드·명세·예제입니다. 패키지 설치 파일까지 포함한 오프라인 ZIP은 프로젝트의 artifacts/dsz_packages 폴더에 별도로 있습니다.")


def render_curation_sources() -> None:
    st.subheader("스마트팜코리아 큐레이션 원자료")
    strawberry_path = DATA / "strawberry_curation_audit.json"
    regional_path = DATA / "regional_curation_manifest.json"
    if not strawberry_path.exists() or not regional_path.exists():
        st.info("원자료 품질 검사를 진행 중입니다.")
        return
    try:
        strawberry_bytes, regional_bytes = strawberry_path.read_bytes(), regional_path.read_bytes()
        strawberry, regional = json.loads(strawberry_bytes), json.loads(regional_bytes)
        if (hashlib.sha256(Path(strawberry["source"]["zip_path"]).read_bytes()).hexdigest() != strawberry["source"]["zip_sha256"]
                or hashlib.sha256((PROJECT / regional["source"]).read_bytes()).hexdigest() != regional["source_sha256"]):
            st.info("원본이 변경되어 큐레이션 자료를 다시 검증해야 합니다.")
            return
    except (OSError, ValueError, KeyError):
        st.info("큐레이션 자료 품질 기록을 갱신 중입니다.")
        return
    labels = {"shipping": "딸기 출하", "growth": "딸기 생육", "environment": "딸기 환경"}
    counts = [{"자료": labels[name], "원본 행": item["rows"], "고유 시설": item["facilities"]}
              for name, item in strawberry["tables"].items()]
    stats = regional["statistics"]
    counts.append({"자료": "지역별 농가 출하·매출", "원본 행": stats["source_rows"], "고유 시설": stats["source_facilities"]})
    st.dataframe(pd.DataFrame(counts), hide_index=True)
    st.write(f"딸기 총출하량 후보 {strawberry['target_candidate_rows']}작기 중 면적·시설정보가 정확히 연결된 {strawberry['metadata_candidate_rows']}작기, 5품목 총매출 후보 {stats['eligible_rows']}작기를 비교에 사용합니다.")
    st.caption("딸기 출하량은 kg/작기, 지역별 자료의 출하량은 정의서상 개/작기입니다. 지역별 매출은 원 단위이며 순이익·비용 정보가 아닙니다. 원본 행 수를 농가 수나 모델 표본 수로 합산하지 않았습니다.")
    st.caption("지역별 파일은 매출 결측이 많고, 면적 정의가 API 수치와 충돌합니다. 중복·충돌·결측과 극단값을 감사표에 보존했습니다. 두 자료 모두 대회 안심구역의 미개방자료와 구분됩니다.")
    for label, content, filename in [("딸기 큐레이션 품질 검사표", strawberry_bytes, strawberry_path.name),
                                     ("지역별 큐레이션 품질 검사표", regional_bytes, regional_path.name)]:
        st.download_button(label, content, file_name=filename, mime="application/json", key=f"download_{filename}")


def main() -> None:
    st.set_page_config(page_title="스마트팜 도입 시뮬레이터", page_icon="🌱", layout="wide")
    apply_dashboard_style()
    st.markdown('<div class="brand"><strong>스마트팜 도입 설계</strong><span>재배 계획에서 투자 판단까지</span></div>', unsafe_allow_html=True)
    data = read_csv(str(DATA / "rda_crop_income.csv"))
    metrics = json.loads((PROJECT / "artifacts" / "model_metrics.json").read_text(encoding="utf-8"))
    overview, calculator, prices, inseason, validation, sources = st.tabs(["한눈에 보기", "도입 전 계산", "가격 예측", "재배 중 점검", "모델 검증", "수집 자료"], key="main_tabs", on_change="rerun")
    with overview:
        render_overview(PROJECT)
    with calculator:
        render_calculator(data, metrics)
    with prices:
        render_price_forecast(PROJECT)
    with inseason:
        render_inseason_analysis(PROJECT)
    with validation:
        section("검증 결과", "복잡한 모델이 항상 더 정확하지는 않았습니다", "좋아진 결과와 좋아지지 않은 결과를 함께 확인합니다.")
        takeaway("경제성 계산은 참고 집계와 입력 가정으로 읽어야 합니다", "이 실험은 신규 농가의 실제 수익률이나 설비 설치 효과를 입증한 결과가 아닙니다.")
        columns = st.columns(3, gap="large")
        with columns[0]:
            st.markdown("### 수량 예측")
            st.write("관측이 적은 조건에서는 과거의 단순 기준값이 유용했습니다.")
        with columns[1]:
            st.markdown("### 가격 예측")
            st.write("2025년 비교에서는 같은 달 최근값의 평균 오차가 더 작았습니다.")
        with columns[2]:
            st.markdown("### 생육 예측")
            st.write("환경을 추가했을 때 정확도가 더 좋아지지는 않았습니다.")
        with st.expander("실험별 검증 방법 · 전체 결과 · 원자료 내려받기"):
            render_validation(metrics)
    with sources:
        section("사용한 데이터", "자료마다 쓰임을 분명하게 나눴습니다", "집계 소득자료와 설비 가격은 투자 계산에, 농가 관측은 별도 예측 실험에 사용합니다.")
        st.dataframe(pd.DataFrame([
            {"어디에 쓰나": "연간 수량·소득·운영비 기준", "사용한 자료": "농촌진흥청 농산물 소득조사", "확인 범위": "2020–2024년 · 공개 집계자료"},
            {"어디에 쓰나": "초기 투자비", "사용한 자료": "스마트팜코리아 등록 설비 3종", "확인 범위": "공개 가격 · 공사비 등은 별도 입력"},
            {"어디에 쓰나": "월별 가격 변화 비교", "사용한 자료": "KAMIS 중도매인 판매가격", "확인 범위": "농가수취단가와 구분"},
            {"어디에 쓰나": "날씨 조건의 참고", "사용한 자료": "기상청 기후평년값", "확인 범위": "1991–2020년 · 실제 기상예보 아님"},
            {"어디에 쓰나": "생육·출하 예측 실험", "사용한 자료": "스마트팜코리아·ADP 농가 관측", "확인 범위": "자료별 단위·품질 검사 후 별도 평가"},
            {"어디에 쓰나": "안심구역 현장 검증 준비", "사용한 자료": "대회 명세서·합성 예제", "확인 범위": "실제 미개방 자료는 현장에서 검증"},
        ]), hide_index=True, width="stretch")
        with st.expander("자료별 상세 범위 · 출처 · 다운로드"):
            render_sources(data)


if __name__ == "__main__":
    main()
