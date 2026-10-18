"""Facility-bound planning inputs; user evidence never becomes verified history."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.farm_economics import evaluate_facility_plan
from src.farm_evidence import load_farm_evidence
from src.planning_models import load_planning_models, predict_plan


SOURCE_LABELS = {
    "직접 세운 계획": "budget",
    "사용자가 보유한 기록": "user_record",
    "대상 시설 견적": "quote",
    "외부 참고자료": "external_reference",
}
COST_LABELS = {
    "seedlings": "모종·종묘",
    "fertilizer_crop_protection": "비료·농약·방제",
    "energy_water": "난방·전기·수도",
    "hired_labor": "고용노동",
    "packaging_transport": "포장·운송·판매 수수료",
    "rent": "임차료",
    "repairs_other": "수리·유지·기타 현금 운영비",
    "depreciation": "연간 감가상각",
    "family_labor": "연간 가족노동 기회비용",
}


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _render_collected_evidence(project: Path) -> None:
    with st.expander("실제로 확보한 동일 농가 연결 자료 확인"):
        try:
            evidence = load_farm_evidence(project)
        except (OSError, ValueError) as exc:
            st.info(f"수집 근거 파일을 확인해야 합니다: {exc}")
            return
        counts = evidence["api"]["counts"]
        st.write(f"스마트팜 API에서 시설·작기번호·작기연도를 확인해 연결한 결과, 생산·수입과 비용 기록이 모두 있는 "
                 f"작기는 **{counts['overlap_cycles']}개 · {counts['overlap_facilities']}시설**입니다. "
                 f"이 중 **딸기는 {counts['strawberry_overlap_cycles']}작기**입니다.")
        st.caption("비용 기록이 있다는 것과 전체 운영비가 완전하다는 것은 다릅니다. 비용 항목의 중복·집계기간·누락 범위가 확인되지 않아 이 기록을 대상 시설의 총비용으로 자동 적용하지 않습니다.")
        cases = evidence["public_cases"]
        st.write(f"별도로 공식 보고서의 개별 농가 사례 **{len(cases['accepted_cases'])}건**에서 "
                 f"시설 조건·조수입·경영비·소득을 같은 사례로 확인하고, 조수입 − 경영비 = 소득을 검산했습니다. "
                 f"검산·출처 요건에서 제외한 사례는 **{len(cases['excluded_cases'])}건**입니다.")
        strawberry = cases["strawberry_cases"]
        if strawberry:
            st.dataframe(pd.DataFrame([{
                "공식 보고서 사례": row["case_id"], "시군": row["city"], "보고연도": row["report_year"],
                "실제 시설면적 (㎡)": row["area_m2"], "조수입 (원/1,000㎡)": row["revenue_krw_per_1000m2"],
                "경영비 (원/1,000㎡)": row["operating_cost_krw_per_1000m2"],
                "보고된 소득 (원/1,000㎡)": row["income_krw_per_1000m2"],
            } for row in strawberry]), hide_index=True)
            source = strawberry[0]
            st.markdown(f"[경기도농업기술원 원문 보고서]({source['source_url']}) · PDF {source['source_pdf_pages']}쪽")
        st.caption("공개 사례는 위 출하 모델의 학습 농가나 지금 입력할 대상 시설과 같다고 연결한 자료가 아닙니다. 작기 기간·행별 수량 단위·전체 설치비가 확인되지 않아 연간 회수기간 검증이나 kg 출하 모델 학습에 넣지 않았습니다. 아래 가상 예시와도 별개입니다.")


def _source(prefix: str) -> dict:
    cols = st.columns([1, 2])
    label = cols[0].selectbox("금액의 근거 구분", list(SOURCE_LABELS), index=None,
                              placeholder="직접 계획·기록·견적·외부자료 구분", key=f"{prefix}_source_kind")
    ref = cols[1].text_input("근거 문서·내역·작성일", key=f"{prefix}_source_ref",
                             placeholder="예: 2026-10-18 작성한 우리 시설 난방·인력 운영계획")
    return {"source_kind": SOURCE_LABELS.get(label), "source_ref": ref}


def _sales(prefix: str, scope: dict) -> list[dict]:
    count = st.number_input("판매 구간 수", min_value=1, max_value=6, value=1, step=1, key=f"{prefix}_count")
    st.caption("판매시기·등급·판로별로 출하량을 배분합니다. 배분 합계는 100%여야 합니다. 수취단가에서 이미 뺀 수수료는 비용에 다시 넣지 마세요.")
    rows = []
    for index in range(count):
        key = f"{prefix}_{index}"
        st.markdown(f"**판매 구간 {index + 1}**")
        cols = st.columns([2, 1, 1])
        label = cols[0].text_input("판로·등급", key=f"{key}_label", placeholder="예: 12~3월 공동선별 상품")
        share = cols[1].number_input("출하량 배분 (%)", min_value=0.0, max_value=100.0,
                                     value=None, key=f"{key}_share")
        price = cols[2].number_input("실제 적용할 수취단가 (원/kg)", min_value=0.0,
                                     value=None, step=100.0, key=f"{key}_price")
        cols = st.columns(2)
        start = cols[0].date_input("판매 시작일", value=None, key=f"{key}_start")
        end = cols[1].date_input("판매 종료일", value=None, key=f"{key}_end")
        rows.append({"scope": scope, **_source(key), "label": label,
                     "share": None if share is None else share / 100,
                     "net_price_krw_per_kg": price, "sale_start": _iso(start), "sale_end": _iso(end)})
    return rows


def _costs(prefix: str, scope: dict) -> list[dict]:
    st.caption("아래 금액은 입력한 시설 전체의 연간 비용입니다. 1,000㎡ 평균을 자동 환산하지 않습니다. 지출이 없는 항목도 확인한 뒤 0을 직접 입력하세요.")
    source = _source(prefix)
    rows = []
    for category, label in COST_LABELS.items():
        cols = st.columns([2, 1, 1])
        cols[0].write(label)
        annual_only = category in {"depreciation", "family_labor"}
        basis = cols[1].selectbox(f"{label} 기준", ["연간 총액"] if annual_only else ["연간 총액", "출하 1kg당"],
                                 key=f"{prefix}_{category}_basis", label_visibility="collapsed")
        amount = cols[2].number_input(f"{label} (원)", min_value=0.0, value=None, step=1000.0,
                                      key=f"{prefix}_{category}", label_visibility="collapsed")
        rows.append({"scope": scope, **source, "category": category,
                     "basis": "annual_total" if basis == "연간 총액" else "per_kg", "amount_krw": amount})
    st.caption("가족노동은 실제 현금 지급과 구분한 노동 가치입니다. 고용노동과 중복 계상하지 않습니다. 감가상각은 소득 계산에 반영하고 현금흐름에서 다시 빼지 않습니다.")
    return rows


def _replacements(prefix: str, horizon: int) -> dict | None:
    policy = st.radio("분석기간 중 교체 지출", ["없음으로 계획", "교체 계획 입력"], index=None,
                      horizontal=True, key=f"{prefix}_policy")
    if policy != "교체 계획 입력":
        return {} if policy is not None else None
    count = st.number_input("교체 횟수", min_value=1, max_value=3, value=1, key=f"{prefix}_count")
    result = {}
    for index in range(count):
        cols = st.columns(2)
        year = cols[0].number_input("도입 후 교체 연도", min_value=1, max_value=horizon,
                                    value=min(index + 1, horizon), key=f"{prefix}_{index}_year")
        amount = cols[1].number_input("해당 연도 교체비 합계 (원)", min_value=0.0, value=None,
                                      step=100000.0, key=f"{prefix}_{index}_amount")
        if str(year) in result:
            st.error("같은 교체 연도는 금액을 합쳐 한 번만 입력하세요.")
            return None
        result[str(year)] = amount
    return result


def load_facility_example() -> None:
    """Fill intentionally fictional inputs, with their provenance left visible."""
    state = {
        "facility_example": True, "fe_plan_id": "가상계획-001", "fe_facility_id": "가상시설-001",
        "fe_area": 1000.0, "fe_cycle_start": date(2026, 9, 1), "fe_cycle_end": date(2027, 6, 30),
        "fe_financial_start": date(2026, 9, 1), "fe_financial_end": date(2027, 8, 31),
        "fe_region": "전라남도", "fe_district": "보성군", "fe_facility_type": "비닐",
        "fe_sales_count": 1, "fe_sales_0_label": "가상 판매계획 · 공동선별 상품",
        "fe_sales_0_share": 100.0, "fe_sales_0_price": 10000.0,
        "fe_sales_0_start": date(2026, 12, 1), "fe_sales_0_end": date(2027, 6, 30),
        "fe_sales_0_source_kind": "직접 세운 계획", "fe_sales_0_source_ref": "가상 입력 예시 · 실제 계약이 아님",
        "fe_costs_source_kind": "직접 세운 계획", "fe_costs_source_ref": "가상 입력 예시 · 실제 장부가 아님",
        "fe_investment_count": 1, "fe_investment_0_label": "가상 온실·재배·제어설비 일괄 계획",
        "fe_investment_0_amount": 100000000.0, "fe_investment_0_source_kind": "직접 세운 계획",
        "fe_investment_0_source_ref": "가상 입력 예시 · 실제 견적이 아님",
        "fe_investment_0_coverage": "예시에서 온실·재배설비·제어설비·설치·부가세 포함으로 가정; 토지구매 제외",
        "fe_investment_confirmed": True, "fe_period_agreed": True, "fe_repeat_agreed": True,
        "fe_mode": "신규 도입", "fe_horizon": 10, "fe_discount": 4.0,
        "fe_replacement_policy": "없음으로 계획", "fe_yield_change": 20.0,
        "fe_price_change": 20.0, "fe_cost_change": 10.0,
        "facility_evidence_target": {"plan_id": "가상계획-001", "facility_id": "가상시설-001", "crop": "딸기",
            "area_m2": 1000.0, "cycle_start": "2026-09-01", "cycle_end": "2027-06-30",
            "financial_start": "2026-09-01", "financial_end": "2027-08-31",
            "variety": "설향", "region": "전라남도", "district": "보성군", "facility_type": "비닐"},
    }
    amounts = [1500000, 1000000, 3500000, 3000000, 1500000, 1000000, 1000000, 5000000, 6000000]
    for (category, _), amount in zip(COST_LABELS.items(), amounts):
        state[f"fe_costs_{category}"] = float(amount)
        state[f"fe_costs_{category}_basis"] = "연간 총액"
    state["facility_evidence_scope"] = dict(state["facility_evidence_target"])
    st.session_state.update(state)
    for key in ["facility_calculation_result", "facility_calculation_payload", "facility_calculation_hash"]:
        st.session_state.pop(key, None)


def clear_facility_inputs() -> None:
    for key in list(st.session_state):
        if key.startswith("fe_") or key.startswith("facility_"):
            st.session_state.pop(key, None)


def _render_result(result: dict, payload: dict) -> None:
    base = next(row for row in result["scenarios"] if row["name"] == "기준")
    st.subheader("이 시설 계획의 계산 결과")
    st.write(f"**{payload['target']['facility_id']} · {payload['target']['area_m2']:,.0f}㎡** · "
             f"{payload['target']['financial_start']} ~ {payload['target']['financial_end']}")
    st.caption("입력한 판매·비용·견적과 모델 출하량을 연결한 계획 계산입니다. 입력 자료의 진위, 실제 미래 소득과 장비 설치 효과가 검증되었다는 뜻은 아닙니다.")
    cols = st.columns(4)
    cols[0].metric("연간 매출", f"{base['annual_revenue_krw']:,.0f}원")
    cols[1].metric("가족노동 반영 연 소득", f"{base['annual_income_after_family_labor_krw']:,.0f}원")
    cols[2].metric("연간 투자 현금흐름", f"{base['annual_incremental_cash_flow_before_replacements_krw']:,.0f}원")
    payback = base["payback_year"]
    cols[3].metric("최초 투자금 회수", "기간 내 미회수" if payback is None else f"{payback}년 말")
    st.write(f"초기 투자비 합계: **{result['initial_capex_krw']:,.0f}원** · 분석기간 **{result['horizon_years']}년**")
    st.write(f"분석기간 말 누적 현금흐름: **{base['undiscounted_balance_krw']:,.0f}원** · "
             f"{'초기 투자금 회수 상태' if base['recovered_by_horizon'] else '초기 투자금 미회수 상태'}")
    if payback is not None and not base["recovered_by_horizon"]:
        st.warning("중간에 초기 투자금을 회수했지만, 이후 교체 지출 등을 반영하면 분석기간 말에는 다시 미회수 상태입니다.")
    st.caption("소득은 감가상각·가족노동 기회비용을 차감합니다. 회수 기간은 가족노동 기회비용 차감 전 현금흐름으로 계산합니다. 기존 시설 개량은 유지안 대비 추가 현금흐름을 사용합니다.")
    rows = []
    for scenario in result["scenarios"]:
        rows.append({"조건": scenario["name"], "연간 출하량 (kg)": scenario["annual_yield_kg"],
                     "매출 (원)": scenario["annual_revenue_krw"],
                     "가족노동 반영 소득 (원)": scenario["annual_income_after_family_labor_krw"],
                     "연간 투자 현금흐름 (원)": scenario["annual_incremental_cash_flow_before_replacements_krw"],
                     "최초 회수 시점": "기간 내 미회수" if scenario["payback_year"] is None else f"{scenario['payback_year']}년 말",
                     "분석기간 말 누적 현금흐름 (원)": scenario["undiscounted_balance_krw"],
                     "분석기간 말 회수 상태": "회수" if scenario["recovered_by_horizon"] else "미회수"})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.markdown("**이 계획을 판단할 때 확인할 기준**")
    cols = st.columns(3)
    required = base.get("required_annual_yield_for_horizon_payback_kg")
    break_even_price = base.get("full_cost_break_even_price_krw_per_kg")
    cash_break_even = base.get("operating_break_even_yield_kg")
    cols[0].metric("현금 운영비를 충당할 출하량", "계산 불가" if cash_break_even is None else f"{cash_break_even:,.0f}kg")
    cols[1].metric("가족노동·상각까지 충당할 단가", "계산 불가" if break_even_price is None else f"{break_even_price:,.0f}원/kg")
    cols[2].metric("분석기간 내 투자 회수에 필요한 출하량", "계산 불가" if required is None else f"{required:,.0f}kg")
    st.caption("입력한 비용·단가가 유지된다는 조건의 기준입니다. 이 출하량을 실제로 달성한다는 예측이나 설치 효과의 증거는 아닙니다.")
    cumulative = pd.DataFrame({row["name"]: row["cumulative_cash_flows_krw"] for row in result["scenarios"]})
    st.line_chart(cumulative.rename_axis("경과 연도"))
    with st.expander("입력 근거 · 계산 내역 · 내려받기"):
        st.json({"대상 시설": result.get("target_context"), "근거 구분": result.get("evidence_summary"),
                 "항목별 예산": result.get("budget"), "검증 범위": result.get("quality")})
        st.dataframe(cumulative)
        st.download_button("시설 계획과 계산 결과 내려받기", json.dumps({"inputs": payload, "results": result},
                           ensure_ascii=False, indent=2), file_name="facility_plan_economics.json",
                           mime="application/json", key="fe_download")


def render_facility_calculator(project: Path) -> None:
    st.subheader("내 시설의 출하·판매·비용·투자 계획")
    st.write("대상 시설과 기간을 먼저 정하고, 그 시설에 적용할 판매 조건·운영비·설비 금액을 연결합니다. 외부 평균은 자동 입력되지 않습니다.")
    _render_collected_evidence(project)
    cols = st.columns(2)
    cols[0].button("가상 입력 예시 불러오기", on_click=load_facility_example, key="fe_example")
    cols[1].button("입력 비우고 새 계획 시작", on_click=clear_facility_inputs, key="fe_clear")
    if st.session_state.get("facility_example"):
        st.warning("가상 입력 예시를 불러온 상태입니다. 예시의 단가·비용·투자비는 실제 농가 자료나 견적이 아닙니다.")
    try:
        bundle = load_planning_models(project)["shipment"]
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"출하 모델 검증 파일을 확인해야 합니다: {exc}")
        return
    support = bundle["support"]["by_crop"]["딸기"]
    with st.expander("01 대상 시설과 재배·계산 기간", expanded=True):
        cols = st.columns(3)
        plan_id = cols[0].text_input("계획 이름·번호", key="fe_plan_id")
        facility_id = cols[1].text_input("대상 시설 이름·번호", key="fe_facility_id")
        area = cols[2].number_input("이 시설의 재배면적 (㎡)", min_value=1.0, value=None, step=100.0, key="fe_area")
        st.caption("새 시설이면 계획용 고유번호를 쓰세요. 이 번호는 기존 학습 농가 ID가 아니라, 아래 입력을 같은 대상에 묶는 번호입니다. 현재 출하 모델 범위: 딸기 · 설향.")
        cols = st.columns(2)
        cycle_start = cols[0].date_input("작기 시작일 · 정식 예정일", value=None, key="fe_cycle_start")
        cycle_end = cols[1].date_input("작기 종료 예정일", value=None, key="fe_cycle_end")
        financial_start = cols[0].date_input("연간 운영계획 시작일", value=None, key="fe_financial_start")
        financial_end = cols[1].date_input("연간 운영계획 종료일", value=None, key="fe_financial_end")
        st.caption("비용·판매계획은 이 연간 기간에 맞춥니다. 작기 전체를 포함하는 365일 또는 366일이며, 현재 1년에 한 작기 기준입니다.")
        cols = st.columns(3)
        region = cols[0].selectbox("시도", support["categories"]["region"], index=None, key="fe_region")
        districts = support.get("locations", {}).get(region, support["categories"]["district"])
        if st.session_state.get("fe_district") not in districts:
            st.session_state.pop("fe_district", None)
        district = cols[1].selectbox("시군구", districts, index=None, key="fe_district")
        facility_type = cols[2].selectbox("온실 피복 유형", support["categories"]["facility_type"], index=None, key="fe_facility_type")
    target = {"plan_id": plan_id, "facility_id": facility_id, "crop": "딸기", "area_m2": area,
              "cycle_start": _iso(cycle_start), "cycle_end": _iso(cycle_end),
              "financial_start": _iso(financial_start), "financial_end": _iso(financial_end),
              "variety": "설향", "region": region, "district": district, "facility_type": facility_type}
    prediction = None
    if area is not None and cycle_start and region and district and facility_type:
        query = {"crop": "딸기", "variety": "설향", "region": region, "district": district,
                 "facility_type": facility_type, "area_m2": area,
                 "planting_year": cycle_start.year, "planting_month": cycle_start.month}
        prediction = predict_plan(bundle, query)
        st.metric("모델이 추정한 한 작기 출하량", f"{prediction['prediction']:,.1f} kg")
        validation = bundle["validation"]["metrics"]
        st.caption(f"학습·검증에 시설이 겹치지 않게 나눈 검증 평균오차: 모델 선택 {validation['nested_selection']['mae']:,.0f}kg, "
                   f"단순 면적당 중앙값 {validation['baseline']['mae']:,.0f}kg. 현재 모델 선택 절차가 단순 기준보다 우수하다고 입증하지 못했습니다.")
        if prediction.get("warnings"):
            st.caption("입력에 학습 범위 밖 면적·범주 또는 검증되지 않은 미래 연도 조건이 있습니다. 예측값은 실제 성과 보장이 아닙니다.")
    else:
        st.info("면적·작기 시작일·지역·온실 유형을 입력하면 판매·비용 입력 전에도 출하 예측을 볼 수 있습니다.")
    if st.button("위 시설·연간기간에 아래 입력 근거 연결", key="fe_bind_scope",
                 disabled=not all(target.values())):
        st.session_state["facility_evidence_scope"] = dict(target)
        st.session_state["facility_evidence_target"] = dict(target)
    scope = st.session_state.get("facility_evidence_scope", {})
    if scope:
        st.caption(f"아래 근거가 적용될 시설: {scope['facility_id']} · {scope['financial_start']} ~ {scope['financial_end']}. 시설·면적·작기·지역 조건을 바꾸면 기존 근거는 자동 재연결되지 않습니다.")
    else:
        st.info("입력 근거를 적용할 시설·기간을 위 버튼으로 연결하세요. 근거의 진위를 인증하는 기능은 아닙니다.")
    with st.expander("02 이 시설의 판매 계획"):
        sales = _sales("fe_sales", scope)
    with st.expander("03 이 시설의 연간 운영비·감가상각·가족노동"):
        costs = _costs("fe_costs", scope)
    with st.expander("04 투자 범위·견적과 분석기간"):
        cols = st.columns(3)
        mode_label = cols[0].selectbox("사업 구분", ["신규 도입", "기존 시설 개량"], key="fe_mode")
        horizon = cols[1].number_input("분석기간 (년)", min_value=1, max_value=30, value=10, key="fe_horizon")
        discount = cols[2].number_input("연 할인율 (%)", min_value=0.0, max_value=30.0, value=4.0, key="fe_discount")
        count = st.number_input("투자 항목 수", min_value=1, max_value=6, value=1, key="fe_investment_count")
        investments = []
        for index in range(count):
            key = f"fe_investment_{index}"
            cols = st.columns(2)
            label = cols[0].text_input("설비·공사 항목", key=f"{key}_label")
            amount = cols[1].number_input("해당 항목 초기 투자비 (원)", min_value=0.0, value=None,
                                          step=1000000.0, key=f"{key}_amount")
            coverage = st.text_input("포함·제외 범위", key=f"{key}_coverage",
                                     placeholder="장비 사양·면적·수량·설치·부가세·온실·토목·전기인입 등의 포함 여부")
            investments.append({"scope": scope, **_source(key), "label": label, "amount_krw": amount, "coverage": coverage})
        investment_confirmed = st.checkbox("이 시설에 필요한 투자 범위를 검토했고, 제외 금액과 중복을 확인했습니다.", key="fe_investment_confirmed")
        replacements = _replacements("fe_replacement", horizon)
    baseline = None
    if mode_label == "기존 시설 개량":
        with st.expander("05 개량하지 않고 유지할 때의 같은 시설 계획", expanded=True):
            st.write("회수 기간은 위 도입안과 아래 유지안의 차이로 계산합니다. 장비를 고른 것만으로 출하 증가나 비용 절감이 자동 생성되지 않습니다.")
            baseline_source = _source("fe_baseline")
            baseline_yield = st.number_input("유지안 연간 출하량 (kg)", min_value=0.0, value=None, key="fe_baseline_yield")
            baseline_sales = _sales("fe_baseline_sales", scope)
            baseline_costs = _costs("fe_baseline_costs", scope)
            baseline_replacements = _replacements("fe_baseline_replacement", horizon)
            baseline = {"scope": scope, **baseline_source, "yield_kg": baseline_yield,
                        "sales": baseline_sales, "costs": baseline_costs, "replacements_krw": baseline_replacements}
    with st.expander("조건이 달라질 때 비교"):
        cols = st.columns(3)
        yield_change = cols[0].number_input("출하량 변동 (±%)", min_value=0.0, max_value=90.0, value=20.0, key="fe_yield_change") / 100
        price_change = cols[1].number_input("판매단가 변동 (±%)", min_value=0.0, max_value=90.0, value=20.0, key="fe_price_change") / 100
        cost_change = cols[2].number_input("현금 운영비 변동 (±%)", min_value=0.0, max_value=90.0, value=10.0, key="fe_cost_change") / 100
        st.caption("사용자가 정한 가정 비교입니다. 실제 발생확률·예측구간·설비 효과가 아닙니다. kg당 비용은 시나리오 출하량에 따라 함께 변합니다.")
    period_agreed = st.checkbox("학습 출하 기록의 작기 완결성은 미확인임을 이해하고, 예측값을 이번 한 작기·연간 1작기 계획에 적용합니다.", key="fe_period_agreed")
    repeat_agreed = st.checkbox("분석기간 동안 같은 연간 판매·운영 계획을 반복하고, 입력한 교체 지출만 별도로 반영합니다.", key="fe_repeat_agreed")
    st.caption("이 계산은 세금·대출 원리금·보조금·운전자금 증감·기말 처분가치를 포함하지 않습니다. 소득은 세후 순이익과 다릅니다.")
    payload = {"target": target, "evidence_target": st.session_state.get("facility_evidence_target"),
               "prediction": prediction, "acknowledge_prediction_period": period_agreed,
               "repeat_annual_plan": repeat_agreed, "sales": sales, "costs": costs,
               "investments": investments, "investment_scope_confirmed": investment_confirmed,
               "mode": "new" if mode_label == "신규 도입" else "retrofit", "horizon_years": horizon,
               "discount_rate": discount / 100, "replacements_krw": replacements,
               "scenarios": [
                   {"name": "불리", "yield_multiplier": 1 - yield_change, "price_multiplier": 1 - price_change, "cash_cost_multiplier": 1 + cost_change},
                   {"name": "기준", "yield_multiplier": 1.0, "price_multiplier": 1.0, "cash_cost_multiplier": 1.0},
                   {"name": "유리", "yield_multiplier": 1 + yield_change, "price_multiplier": 1 + price_change, "cash_cost_multiplier": 1 - cost_change}]}
    if baseline is not None:
        payload["baseline"] = baseline
    ready, result = True, None
    try:
        result = evaluate_facility_plan(payload)
    except ValueError as exc:
        ready = False
        st.info(f"입력 확인 필요: {exc}")
    fingerprint = _fingerprint(payload)
    if st.session_state.get("facility_calculation_hash") not in {None, fingerprint}:
        st.info("입력이 변경되어 이전 결과를 숨겼습니다. 시설·기간·근거를 확인하고 다시 계산하세요.")
        st.session_state.pop("facility_calculation_result", None)
        st.session_state.pop("facility_calculation_payload", None)
        st.session_state.pop("facility_calculation_hash", None)
    if st.button("이 시설 계획 계산", type="primary", disabled=not ready, key="fe_calculate"):
        st.session_state["facility_calculation_result"] = result
        st.session_state["facility_calculation_payload"] = payload
        st.session_state["facility_calculation_hash"] = fingerprint
    if ready and st.session_state.get("facility_calculation_hash") == fingerprint:
        _render_result(st.session_state["facility_calculation_result"], payload)
