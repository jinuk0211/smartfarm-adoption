"""Equipment selection and visual summaries for the planning dashboard."""

from __future__ import annotations

import json
import hashlib
import base64
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

from src.equipment_costs import estimate_equipment_cost, load_catalog
from src.risk_simulation import simulate_plan
from src.scenario_assumptions import relative_market_price
from src.dashboard_ui import apply_style, section, stat, takeaway


def apply_dashboard_style() -> None:
    apply_style()


def load_example_inputs() -> None:
    """Load transparent example assumptions; never claim an actual farm quote."""
    st.session_state.update({
        "crop": "딸기", "category": "시설딸기(수경)", "region": "전국",
        "area": 1000.0, "planned_year": 2027, "yield_mode": "실험 모델",
        "mode": "신규 도입", "capex_source": "장비 구성으로 계산",
        "equipment_ids": ["5126", "6337"], "equipment_options_6337": ["6337-option-1"],
        "equipment_qty_5126": 1, "equipment_qty_6337": 1,
        "equipment_installation": 5_000_000, "equipment_vat": 2_957_300,
        "equipment_other": 80_000_000, "horizon": 10, "discount": 4.0,
        "yield_change": 10.0, "price_change": 20.0, "cost_change": 10.0,
        "has_replacement": False, "example_loaded": True,
        "use_market_transfer": False, "use_weather_scenario": False,
        "main_tabs": "도입 전 계산",
    })
    for key in ["calculation_result", "calculation_payload"]:
        st.session_state.pop(key, None)


def render_equipment_selector(project: Path) -> tuple[float | None, dict | None]:
    path = project / "data" / "processed" / "equipment_catalog.json"
    if not path.exists():
        st.info("장비 가격 카탈로그를 준비한 뒤 구성별 계산을 사용할 수 있습니다.")
        return None, None
    catalog = load_catalog(path)
    packages = catalog["packages"]
    selected = st.multiselect(
        "설치할 장비 패키지", list(packages), key="equipment_ids",
        format_func=lambda key: f"{packages[key]['name']} · {packages[key]['package_price_krw'] / 10000:,.1f}만원",
    )
    st.caption("2026-10-10 확인한 스마트팜코리아 등록 표준가격입니다. 실제 거래 견적·설치 가능 면적·장비 간 호환성은 확인되지 않았습니다. 패키지 내부 부품 가격은 다시 더하지 않습니다.")
    if sum(packages[key].get("category") == "fertigation" for key in selected) > 1:
        st.warning("양액기 두 종류를 함께 선택했습니다. 대안 장비인지 확인해 중복 투자를 피하세요.")
    selections = []
    for key in selected:
        package = packages[key]
        columns = st.columns([1, 3])
        quantity = columns[0].number_input(f"{package['name']} 세트 수", min_value=1, max_value=100, value=1, step=1, key=f"equipment_qty_{key}")
        options = {item["option_id"]: item for item in package["options"]}
        option_ids = columns[1].multiselect(
            f"{package['name']} 추가 옵션", list(options), key=f"equipment_options_{key}",
            format_func=lambda option: f"{options[option]['name']} · {options[option]['price_krw'] / 10000:,.1f}만원/세트",
        ) if options else []
        selections.append({"equipment_id": key, "quantity": int(quantity), "option_ids": option_ids})
    if not selections:
        st.info("장비를 선택하거나 직접 견적 입력 방식을 사용하세요.")
        return None, None
    columns = st.columns(3)
    installation = columns[0].number_input("장비 설치 공사 추가비 (원)", min_value=0, value=None, step=100000, key="equipment_installation")
    vat = columns[1].number_input("추가 반영할 부가세 (원)", min_value=0, value=None, step=100000, key="equipment_vat")
    other = columns[2].number_input("온실·토목·기타 장비 등 추가 투자비 (원)", min_value=0, value=None, step=1000000, key="equipment_other")
    st.caption("포함 여부를 확인한 금액 또는 명시적 가정을 입력하세요. 추가 지출이 없으면 0을 직접 입력합니다. 온실 기준 단가에 ICT가 포함된 경우 장비비를 중복 합산하지 마세요.")
    result = estimate_equipment_cost(catalog, selections, installation_krw=installation, additional_vat_krw=vat)
    total = None if result["initial_capex_krw"] is None or other is None else result["initial_capex_krw"] + other
    columns = st.columns(2)
    columns[0].metric("선택 장비·옵션 소계", f"{result['equipment_subtotal_krw'] / 10000:,.1f}만원")
    columns[1].metric("경제성 계산에 반영할 전체 투자비", "추가비 확인 필요" if total is None else f"{total / 10000:,.1f}만원")
    st.markdown("[스마트팜코리아 장비 등록가격 출처](https://www.smartfarmkorea.net/company/equipmentInfo.do)")
    return total, {"equipment": result, "other_capex_krw": other, "total_initial_capex_krw": total,
                   "interpretation": "등록 표준가격과 사용자가 입력한 추가비용 가정. 실제 농가 견적이 아님"}


def render_overview(project: Path) -> None:
    illustration = project / "assets/design/strawberry-greenhouse-editorial.png"
    background = ""
    if illustration.exists():
        encoded = base64.b64encode(illustration.read_bytes()).decode("ascii")
        background = f' style="background-image:linear-gradient(90deg,#f7f5ee 0%,#f7f5ee 35%,transparent 80%),url(data:image/png;base64,{encoded});"'
    st.markdown(f'<div class="home-hero"{background}><p class="eyebrow">스마트팜 도입을 고민하는 당신에게</p>'
                '<h1 class="hero-title">얼마를 투자하고,<br><em>얼마를 남길 수 있을까?</em></h1>'
                '<p class="hero-description">작물과 면적, 필요한 설비를 고르면<br>연간 소득과 투자금 회수 시점을 함께 비교합니다.</p></div>',
                unsafe_allow_html=True)
    st.button("딸기 계획 예시 불러오기", on_click=load_example_inputs, type="primary", key="load_example")
    demo_path = project / "artifacts" / "planning_demo.json"
    if demo_path.exists():
        demo = json.loads(demo_path.read_text(encoding="utf-8"))
        from src.economics import evaluate_plan
        result = evaluate_plan(demo["inputs"])
        base = next(item for item in result["scenarios"] if item["name"] == "기준")
        st.markdown('<div class="example-heading"><strong>딸기 1,000㎡라면</strong>'
                    '<span>전국 소득조사 + 공개 장비가격 + 비용 가정으로 계산한 예시</span></div>', unsafe_allow_html=True)
        columns = st.columns([1, 1.08, .95], gap="large")
        with columns[0]:
            stat("처음 필요한 투자금", f"{result['initial_capex_krw'] / 100000000:.2f}억원", "장비·온실·공사비·추가 부가세 포함")
        with columns[1]:
            stat("자가노동까지 반영한 연 소득", f"{base['annual_income_after_family_labor_krw'] / 10000:,.0f}만원", "감가상각 및 가족노동 기회비용 반영", emphasis=True)
        with columns[2]:
            stat("투자금을 회수하는 시점", f"{base['payback_year']}년 말", "자가노동 기회비용 차감 전 현금흐름 기준")
        st.caption("예시의 공사비·온실비·추가 부가세는 가정입니다. 실제 농가의 수익이나 장비 도입 효과를 보장하는 결과가 아닙니다.")
    st.markdown('<div class="journey"><p><b>01 재배 계획</b>무엇을, 얼마나 키울지</p>'
                '<p><b>02 투자 계획</b>어떤 설비에 얼마를 쓸지</p><p><b>03 조건 비교</b>가격이 떨어져도 괜찮을지</p></div>', unsafe_allow_html=True)
    with st.expander("이 계산의 근거와 기획서"):
        st.caption("첫 화면의 온실은 AI로 제작한 컨셉 일러스트입니다.")
        st.write("수량·운영비는 농촌진흥청 소득조사, 설비비는 공개 등록가격을 참고합니다. 공사비 등은 사용자가 직접 입력합니다. 장비 선택만으로 생산량이 늘어난다고 가정하지 않습니다.")
        st.write("대회 미개방 자료는 명세서와 합성 예제로 실행을 준비했습니다. 실제 자료를 이용한 성능 검증은 안심구역에서 진행해야 합니다.")
        deck = project / "presentation" / "smartfarm_proposal.pptx"
        if deck.exists():
            st.download_button("기획서 PPT 다운로드", deck.read_bytes(), file_name=deck.name,
                               mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")


def render_risk_distribution(payload: dict) -> None:
    widths = payload.get("sensitivity_half_widths") or {"yield": abs(1 - payload["scenarios"][0]["yield_multiplier"]),
              "price": abs(1 - payload["scenarios"][0]["price_multiplier"]),
              "cash_cost": abs(1 - payload["scenarios"][0]["cash_cost_multiplier"])}
    result = simulate_plan(payload, uncertainty=widths, n_samples=2000, seed=42, scenario_index=1)
    st.subheader("조건이 달라지면 결과는 얼마나 흔들릴까?")
    st.caption("정한 범위 안에서 출하량·가격·비용을 바꾼 2,000가지 가정 비교입니다. 실제 발생확률이나 신뢰구간이 아닙니다.")
    quantiles = result["quantiles"]["npv_krw"]
    columns = st.columns(3)
    for column, key, label in zip(columns, ["p05", "p50", "p95"], ["하위 5% 경계", "중앙값", "상위 5% 경계"]):
        column.metric(f"가정 분포 NPV · {label}", f"{quantiles[key] / 10000:,.0f}만원")
    samples = pd.DataFrame({"NPV (만원)": [row["npv_krw"] / 10000 for row in result["samples"]]})
    chart = alt.Chart(samples).mark_bar(color="#2d8a64").encode(
        x=alt.X("NPV (만원):Q", bin=alt.Bin(maxbins=35)),
        y=alt.Y("count():Q", title="가정 조합 수"), tooltip=[alt.Tooltip("count():Q", title="조합 수")],
    ).properties(height=240)
    st.altair_chart(chart, width="stretch")
    with st.expander("변동 비교의 가정 · 결과 내려받기"):
        st.write("설정한 ±변동폭의 삼각분포를 사용합니다. 출하·가격·현금비용은 서로 독립이며, 각 조합의 조건은 분석기간 내내 유지합니다. 초기 투자비·감가상각·기존 유지안·교체비·할인율은 고정합니다.")
        st.caption("NPV는 미래 현금흐름을 현재 가치로 할인한 뒤 초기 투자금을 뺀 값입니다. 자가노동 기회비용은 위 소득 지표에서 별도로 확인하세요.")
        st.download_button("변동 비교 결과 내려받기", json.dumps({"inputs": payload, "sensitivity": result}, ensure_ascii=False, indent=2),
                           file_name="smartfarm_sensitivity.json", mime="application/json", key="download_risk")


def render_reference_scenarios(project: Path, crop: str, planned_year: int) -> tuple[dict, bool]:
    result = {"price_multiplier": 1.0, "yield_multiplier": 1.0, "cash_cost_multiplier": 1.0,
              "market": None, "weather": None}
    ready = True
    with st.expander("가격·날씨 참고자료를 계획 가정에 연결"):
        use_market = st.checkbox("도매가격 상대 변화율을 내 판매가격 변화 가정으로 적용", key="use_market_transfer")
        if use_market:
            metrics_path = project / "artifacts/price_forecast_metrics.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
            if metrics is None or not price_result_is_current(project, metrics):
                st.info("검증된 가격 결과를 준비한 뒤 적용할 수 있습니다.")
                ready = False
            else:
                series = [item for item in metrics["series"] if item["crop"] == crop]
                if not series:
                    st.info("이 품목은 연결 가능한 kg 단위 가격 시계열이 없습니다.")
                    ready = False
                else:
                    index = st.selectbox("연결할 가격 품종·등급", range(len(series)),
                                         format_func=lambda i: f"{series[i]['variety']} · {series[i]['grade']}", key=f"transfer_series_{crop}")
                    item = series[index]
                    method = st.radio("가격 변화 참고 방법", ["같은 달 최근값", "2024년에 선택한 모델"], horizontal=True, key="transfer_method")
                    column = "baseline_forecast_krw_per_kg" if method == "같은 달 최근값" else "forecast_krw_per_kg"
                    old = pd.read_csv(project / "artifacts/price_forecast_holdout_predictions.csv", encoding="utf-8-sig")
                    new = pd.read_csv(project / "artifacts/price_forecast_forecast.csv", encoding="utf-8-sig")
                    mask = (old.crop == crop) & (old.variety == item["variety"]) & (old.grade == item["grade"])
                    defaults = [int(month[-2:]) for month in old.loc[mask, "year_month"]]
                    months = st.multiselect("판매가격을 비교할 달 · 각 달 출하량이 같다는 가정", range(1, 13), default=defaults,
                                            format_func=lambda month: f"{month}월", key=f"transfer_months_{crop}_{index}_{method}")
                    try:
                        comparison = relative_market_price(old, new, crop=crop, variety=item["variety"], grade=item["grade"], months=months, method=column)
                        result["price_multiplier"] = comparison["factor"]
                        result["market"] = {**comparison, "source_metrics_sha256": hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
                                            "applied_planned_year": planned_year}
                        st.write(f"선택한 월의 평균 도매가격 변화 **{(comparison['factor'] - 1) * 100:+.1f}%**를 농가수취 기준단가의 변화 가정으로 적용합니다.")
                        st.dataframe(pd.DataFrame(comparison["comparison"]).rename(columns={"month": "월", "actual_2025_krw_per_kg": "2025 실제 (원/kg)", "forecast_2026_krw_per_kg": "2025년 말 기준 2026 전망 (원/kg)"}), hide_index=True)
                    except ValueError as error:
                        st.info(str(error))
                        ready = False
                    st.caption(f"2025년 실제값과 2025년 말에 만든 2026년 전망의 상대 변화입니다. {planned_year}년의 실제 가격 예측으로 검증된 값이 아닙니다. 도매·농가 가격이 같은 비율로 움직이고 선택한 월마다 같은 kg을 판매한다는 사용자 가정입니다.")
        use_weather = st.checkbox("날씨 조건에 따른 출하량·현금비용 가정 적용", key="use_weather_scenario")
        if use_weather:
            climate = pd.read_csv(project / "data/processed/climate_normals_monthly.csv", encoding="utf-8-sig")
            stations = climate[["station_id", "station_name"]].drop_duplicates().set_index("station_id")["station_name"].to_dict()
            columns = st.columns(3)
            station = columns[0].selectbox("직접 선택한 참고 관측지점", list(stations), format_func=lambda value: f"{stations[value]} ({value})", key="weather_station")
            month = columns[1].selectbox("참고 재배 월", range(1, 13), key="weather_month")
            label = columns[2].selectbox("비교할 날씨 조건", ["고온", "저온", "강풍·태풍", "사용자 지정"], key="weather_condition")
            normal = climate.loc[(climate.station_id == station) & (climate.month == month)].iloc[0]
            st.write(f"{stations[station]} {month}월 평년 평균기온 **{normal['mean_temperature_c']:.1f}℃**, 평년 강수량 **{normal['monthly_precipitation_mm']:.1f}mm**")
            st.caption("기상청 1991~2020 기후평년값입니다. 실제 예정 작기의 기상예보나 온실 내부 조건이 아니며, 관측지점을 농가 위치와 자동 연결하지 않습니다.")
            columns = st.columns(2)
            quantity = columns[0].number_input("날씨에 따른 연간 출하량 변화 가정 (%)", min_value=-90.0, max_value=200.0, value=None, step=1.0, key="weather_yield_change")
            cost = columns[1].number_input("날씨에 따른 연간 현금 운영비 변화 가정 (%)", min_value=-90.0, max_value=300.0, value=None, step=1.0, key="weather_cost_change")
            st.caption("참고 월의 날씨 조건이 연간 총량에 미치는 영향을 사용자가 가정합니다. 학습된 효과가 아닙니다. 적용하지 않을 항목은 0을 입력하세요. 아래 ±변동폭은 이 조건을 중심으로 추가 적용합니다.")
            if quantity is None or cost is None:
                ready = False
            else:
                result["yield_multiplier"] = 1 + quantity / 100
                result["cash_cost_multiplier"] = 1 + cost / 100
                result["weather"] = {"condition": label, "station_id": int(station), "station_name": stations[station], "month": month,
                    "normal_period": "1991–2020", "normal_mean_temperature_c": float(normal["mean_temperature_c"]),
                    "normal_monthly_precipitation_mm": float(normal["monthly_precipitation_mm"]),
                    "user_yield_change_percent": quantity, "user_cash_cost_change_percent": cost,
                    "scope": "annual_total_effect",
                    "interpretation": "Explicit user effects; not learned causal weather response or weather forecast",
                    "source_url": "https://data.kma.go.kr/normals/info1.do"}
            st.markdown("[기상청 기후평년값 출처](https://data.kma.go.kr/normals/info1.do)")
    return result, ready


def price_result_is_current(project: Path, result: dict) -> bool:
    """Keep reported accuracy tied to the exact input, model code and CSVs."""
    source = project / "data" / "processed" / "kamis_wholesale_monthly_kg.csv"
    try:
        if hashlib.sha256(source.read_bytes()).hexdigest() != result["input_sha256"]:
            return False
        if set(result.get("source_sha256", {})) != {"src/price_forecast.py", "scripts/run_price_forecast.py"}:
            return False
        if set(result.get("output_sha256", {})) != {f"price_forecast_{name}.csv" for name in ["forecast", "holdout_predictions", "validation_predictions"]}:
            return False
        for name, expected in result["source_sha256"].items():
            if hashlib.sha256((project / name).read_bytes()).hexdigest() != expected:
                return False
        for name, expected in result["output_sha256"].items():
            if hashlib.sha256((project / "artifacts" / name).read_bytes()).hexdigest() != expected:
                return False
    except (OSError, KeyError, TypeError):
        return False
    return True


def render_monthly_prices(frame: pd.DataFrame, series: list[str], colors: list[str]) -> None:
    """Show missing months as gaps and retain isolated observed prices."""
    long = frame[["월", *series]].melt("월", var_name="가격 구분", value_name="가격 (원/kg)")
    chart = alt.Chart(long).mark_line(point=True, strokeWidth=2, invalid="break-paths-show-domains").encode(
        x=alt.X("월:O", sort=[f"{month:02d}월" for month in range(1, 13)], axis=alt.Axis(labelAngle=0, title=None)),
        y=alt.Y("가격 (원/kg):Q", title="원/kg"),
        color=alt.Color("가격 구분:N", scale=alt.Scale(domain=series, range=colors), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["월:O", "가격 구분:N", alt.Tooltip("가격 (원/kg):Q", format=",.0f")],
    ).properties(height=230).configure_view(stroke=None)
    st.altair_chart(chart, width="stretch")


def render_price_forecast(project: Path) -> None:
    section("가격 변화 살펴보기", "출하하는 달에 따라 가격은 달라집니다", "실제 가격과 예측을 나란히 비교해, 계획에 쓸 가격을 신중하게 정하세요.")
    path = project / "artifacts" / "price_forecast_metrics.json"
    if not path.exists():
        st.info("가격 실험을 실행하면 이 화면에 검증 결과를 표시합니다.")
        return
    result = json.loads(path.read_text(encoding="utf-8"))
    if not price_result_is_current(project, result):
        st.info("가격 자료·코드·결과가 변경되었습니다. 가격 실험을 다시 실행하세요.")
        return
    if result["holdout_selected"]["mae_krw_per_kg"] > result["holdout_baseline"]["mae_krw_per_kg"]:
        takeaway("이번 비교에서는 단순 기준값이 더 정확했습니다", f"2025년 전체 평균 오차는 같은 달 최근값 {result['holdout_baseline']['mae_krw_per_kg']:,.0f}원/kg, 선택 모델 {result['holdout_selected']['mae_krw_per_kg']:,.0f}원/kg입니다. 작을수록 실제 가격에 가깝습니다.")
    series = result["series"]
    selected = st.selectbox("가격 품목·품종·등급", range(len(series)),
                            format_func=lambda i: " · ".join(series[i][key] for key in ["crop", "variety", "grade"]), key="price_series")
    item = series[selected]
    holdout = pd.read_csv(project / "artifacts" / "price_forecast_holdout_predictions.csv", encoding="utf-8-sig")
    forecast = pd.read_csv(project / "artifacts" / "price_forecast_forecast.csv", encoding="utf-8-sig")
    def matching(frame: pd.DataFrame) -> pd.DataFrame:
        mask = pd.Series(True, index=frame.index)
        for key in ["crop", "variety", "grade"]:
            mask &= frame[key] == item[key]
        return frame.loc[mask].sort_values("year_month")
    actual = matching(holdout)
    future = matching(forecast)
    columns = st.columns(2)
    with columns[0]:
        st.markdown("**2025년 실제값과 예측값**")
        if actual.empty:
            st.info("2025년 검증 가능한 실제 가격이 없습니다.")
        else:
            calendar = [f"2025-{month:02d}" for month in range(1, 13)]
            plot = actual.set_index("year_month").reindex(calendar).rename_axis("연월").reset_index()
            plot = plot.rename(columns={"actual_krw_per_kg": "실제 가격", "prediction_krw_per_kg": "선택 방법", "baseline_krw_per_kg": "단순 기준값"})
            plot["월"] = plot["연월"].str[-2:] + "월"
            render_monthly_prices(plot, ["실제 가격", "선택 방법", "단순 기준값"], ["#245b3e", "#bd8748", "#a3b796"])
    with columns[1]:
        st.markdown("**2025년 말 기준 2026년 전망**")
        plot = future.rename(columns={"year_month": "연월", "forecast_krw_per_kg": "선택 방법 (원/kg)", "baseline_forecast_krw_per_kg": "단순 기준값 (원/kg)"})
        plot["월"] = plot["연월"].str[-2:] + "월"
        render_monthly_prices(plot, ["선택 방법 (원/kg)", "단순 기준값 (원/kg)"], ["#bd8748", "#a3b796"])
    st.caption("오른쪽은 2025년 말에 만든 당시 전망이며 현재 실시간 예측이 아닙니다. 관측·계절 자료가 부족한 달은 비워 두었습니다.")
    st.caption("KAMIS 도매시장 가격은 농가가 실제 받는 가격과 다릅니다. 경제성 계산의 판매단가를 자동으로 대체하지 않습니다.")
    with st.expander("시계열별 오차와 월별 전망 수치"):
        st.write(f"{result['observed_kg_rows']:,}개의 실제 가격을 사용했습니다. 2021~2023년 자료로 학습하고 2024년으로 방법을 골랐으며, 2025년은 학습·선택에 사용하지 않았습니다.")
        st.caption("전체 평균 오차는 서로 다른 가격대의 품목을 합친 값입니다. 품목별 자료가 없는 달은 0원으로 바꾸지 않았습니다.")
        methods = {"seasonal_last": "같은 달 최근값", "seasonal_median": "같은 달 과거 중앙값", "seasonal_ridge": "계절성을 반영한 회귀 모델"}
        st.write(f"선택한 방법: **{methods.get(item['selected_model'], item['selected_model'])}**")
        comparison = pd.DataFrame([{"방법": label, "검증한 월": score.get("evaluated_months"), "평균 절대 오차 (원/kg)": score.get("mae_krw_per_kg"), "비율 오차 (%)": score.get("wape_percent")}
                                  for label, score in [("선택 모델", item["holdout_selected"]), ("같은 달 최근값", item["holdout_baseline"])]])
        st.dataframe(comparison.round(1), hide_index=True)
        st.dataframe(plot[["월", "선택 방법 (원/kg)", "단순 기준값 (원/kg)"]].round(0), hide_index=True)
        st.download_button("가격 검증 결과 내려받기", path.read_bytes(), file_name=path.name, mime="application/json")
        st.markdown("[KAMIS 가격 정보 출처](https://www.kamis.or.kr/customer/price/wholesale/period.do)")


def render_inseason_analysis(project: Path) -> None:
    section("재배 중 점검", "일주일 뒤, 얼마나 자라 있을까?", "현재 생육과 지난 환경 기록으로 7일 뒤 시설의 평균 초장(식물 높이)을 비교한 실험입니다.")
    path = project / "artifacts/inseason_metrics.json"
    if not path.exists():
        st.info("환경·생육 자료를 연결한 실험 결과를 준비하면 표시합니다.")
        return
    result = json.loads(path.read_text(encoding="utf-8"))
    try:
        hashes = result.get("source_hashes", {})
        if not hashes or any(hashlib.sha256((project / name).read_bytes()).hexdigest() != value for name, value in hashes.items()):
            st.info("생육 실험의 자료·코드가 변경되었습니다. 다시 실행한 결과가 필요합니다.")
            return
        if hashlib.sha256((project / "artifacts/inseason_oof_private.csv").read_bytes()).hexdigest() != result["private_oof_sha256"]:
            st.info("생육 검증 예측이 변경되었습니다. 실험을 다시 실행하세요.")
            return
    except OSError:
        st.info("생육 결과의 출처를 검증하는 로컬 자료가 필요합니다.")
        return
    counts = result["source_counts"]
    takeaway("환경을 추가해도, 이번에는 오차가 더 줄지 않았습니다", "40쌍의 방문 기록에서는 생육만 사용한 방법이 가장 정확했습니다. 적은 표본의 탐색 결과이며 수확량·수익 예측과는 별개입니다.")
    labels = {"current_height": "현재 높이 그대로", "catboost_growth": "생육 기록만 사용",
              "catboost_growth_environment": "생육 + 환경 · 방법 1", "xgboost_growth_environment": "생육 + 환경 · 방법 2"}
    scores = pd.DataFrame([{"방법": labels[row["model"]], "MAE (mm)": row["mae_mm"], "RMSE (mm)": row["rmse_mm"]} for row in result["models"]])
    chart = alt.Chart(scores).mark_bar(cornerRadiusEnd=3, height=26).encode(
        y=alt.Y("방법:N", sort=None, axis=alt.Axis(labelLimit=250, labelFontSize=13)), x=alt.X("MAE (mm):Q", title="평균 절대 오차 (mm), 작을수록 좋음"),
        color=alt.condition(alt.datum["방법"] == "생육 기록만 사용", alt.value("#265b3d"), alt.value("#b8c5ab")),
        tooltip=["방법:N", alt.Tooltip("MAE (mm):Q", format=".2f")],
    ).properties(height=220)
    st.altair_chart(chart, width="stretch")
    st.caption("같은 시설은 학습과 검증에 나누어 넣지 않았습니다. 21개 시설의 40쌍 방문 기록을 5개 그룹으로 나눠 비교했습니다.")
    examples = pd.DataFrame(result["illustrative_holdout_examples"]).rename(columns={
        "group": "현재 초장 구간", "pairs": "방문 쌍", "current_height_mm_mean": "현재 평균 (mm)",
        "observed_next_height_mm_mean": "7일 뒤 실제 평균 (mm)", "predicted_next_height_mm_mean": "검증 예측 평균 (mm)"})
    with st.expander("실제값과 예측값 · 사용한 정보 · 실험 방법"):
        st.dataframe(scores.round(1), hide_index=True)
        st.caption("생육만 사용: CatBoost · 생육+환경 방법 1: CatBoost · 방법 2: XGBoost")
        st.markdown("**전체 검증 기록을 초장 순서로 나눈 네 구간**")
        st.dataframe(examples.round(1), hide_index=True)
        st.caption("좋은 사례만 고르지 않고 전체 검증 쌍을 네 구간으로 요약했습니다. 같은 개체의 연속 성장량이 아니라 방문별 관측 표본 평균입니다.")
        st.write("생육: 현재 초장·엽수·엽장·엽폭·관부직경, 정식 후 일수, 이전 조사 간격과 초장 변화")
        st.write("환경: 조사일 이전 7일·28일의 온도·습도·CO₂ 기록. 조사 당일과 미래 기록은 제외했습니다.")
        st.caption(f"생육 원본 {counts['growth_raw_rows']:,}행, 환경 원본 {counts['environment_raw_rows']:,}행 중 초장(mm) {counts['height_raw_rows_mm']}행을 시설·방문별로 집계했습니다. 온도·습도는 일평균 기록이며 CO₂는 분석일 기준 기록입니다.")
    with st.expander("분석 범위와 자료 제약"):
        for note in result["limitations"]:
            st.write(note)
        st.download_button("생육 검증 결과 내려받기", path.read_bytes(), file_name=path.name, mime="application/json", key="download_inseason")
