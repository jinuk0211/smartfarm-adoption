"""Local interactive farm forecast inputs; annualization remains explicit."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.planning_models import load_planning_models, predict_plan


def render_farm_prediction(project: Path, crop: str, area: float, year: int) -> tuple[dict | None, bool]:
    path = project / "reports/planning_models.json"
    if not path.exists():
        st.info("자료 검증·모델 학습을 먼저 실행해야 농가 예측을 계산에 연결할 수 있습니다.")
        return None, False
    try:
        models = load_planning_models(project)
    except (OSError, ValueError, KeyError):
        st.info("모델과 검증 보고서가 일치하지 않습니다. 자료 검증을 다시 실행해주세요.")
        return None, False
    options = {"작기 출하량 × 조사 판매단가": "shipment", "작기 총매출 예측": "revenue"}
    options = {label: name for label, name in options.items() if crop in models[name]["support"]["crops"]}
    if not options:
        st.info("이 품목을 지원하는 농가 모델이 없습니다.")
        return None, False
    label = st.radio("농가 모델의 계산 기준", list(options), key="farm_model_target")
    target = options[label]
    bundle = models[target]
    support = bundle["support"]["by_crop"][crop]
    defaults = bundle["example_query"] if crop == "딸기" else {}
    columns = st.columns(3)
    query = {"crop": crop, "area_m2": area, "planting_year": year}
    for index, name in enumerate(["variety", "region", "district", "facility_type"]):
        labels = {"variety": "품종", "region": "농가 모델 지역", "district": "시군구", "facility_type": "시설유형"}
        values = support["categories"][name]
        if name == "district":
            values = support.get("locations", {}).get(query["region"], values)
        default = defaults.get(name, values[0])
        query[name] = columns[index % 3].selectbox(labels[name], values,
                                                 index=values.index(default) if default in values else 0,
                                                 key=f"farm_{target}_{crop}_{name}")
    query["planting_month"] = columns[1].number_input("정식 월", min_value=1, max_value=12, value=9, key="farm_planting_month")
    prediction = predict_plan(bundle, query)
    units = "kg" if target == "shipment" else "원"
    method = {"crop_area_median": "품목별 면적당 중앙값", "catboost_log_density": "CatBoost", "xgboost_log_density": "XGBoost"}[prediction["model"]]
    st.write(f"작기 예측 **{prediction['prediction']:,.1f} {units}** · {method}")
    validation = bundle["validation"]["metrics"]
    st.caption(f"농가를 나눈 중첩 검증 평균오차: 모델 선택 {validation['nested_selection']['mae']:,.1f} {units}, 면적당 중앙값 {validation['baseline']['mae']:,.1f} {units}. 내부 실험이며 미래 농가 성능은 검증되지 않았습니다.")
    if validation["nested_selection"]["mae"] > validation["baseline"]["mae"]:
        st.caption("현재 모델 선택 절차는 단순 기준보다 평균 오차가 큽니다. 예측값을 비교하는 용도로 사용하세요.")
    if prediction["warnings"]:
        st.caption("선택 조건에 관측하지 않은 범주·면적 또는 미래연도 조건이 포함됩니다. 미래 농가의 실제 성과를 검증한 예측은 아닙니다.")
    agreed = st.checkbox("기록된 작기 예측을 연 1작기로 가정하고, 선택한 소득조사의 연간 비용을 적용합니다.", key="farm_period_agreement")
    st.caption("설비 도입 효과와 수익 정확도를 검증한 결과는 아닙니다. 모델 예측을 입력 가정으로 연결합니다.")
    return prediction, agreed
