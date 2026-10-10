"""Reproduce the dashboard's illustrative strawberry investment plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from src.economics import evaluate_plan  # noqa: E402
from src.equipment_costs import load_catalog, estimate_equipment_cost  # noqa: E402
from src.risk_simulation import simulate_plan  # noqa: E402
from src.smartfarm_model import predict_yield  # noqa: E402


def build_example() -> dict:
    data = pd.read_csv(ROOT / "data/processed/rda_crop_income.csv", encoding="utf-8-sig")
    row = data.loc[(data.year == 2024) & (data.crop_original == "시설딸기(수경)") & (data.region == "전국")].iloc[0]
    query = {"year": 2027, "crop": "딸기", "cultivation_type": row.cultivation_type,
             "region": "전국", "source_category": row.crop_original}
    prediction = predict_yield(ROOT / "artifacts/rda_0.pkl", query)
    catalog = load_catalog(ROOT / "data/processed/equipment_catalog.json")
    equipment = estimate_equipment_cost(catalog, [
        {"equipment_id": "5126", "quantity": 1},
        {"equipment_id": "6337", "quantity": 1, "option_ids": ["6337-option-1"]},
    ], installation_krw=5_000_000, additional_vat_krw=2_957_300)
    other = 80_000_000
    fields = ["farmgate_price_krw_per_kg", "operating_cost_krw_per_1000m2",
              "depreciation_krw_per_1000m2", "family_labor_cost_krw_per_1000m2"]
    benchmark = {field: float(row[field]) for field in fields}
    benchmark.update(yield_kg_per_1000m2=prediction["yield_kg_per_1000m2"], period_basis=row.period_basis)
    payload = {
        "benchmark": benchmark, "area_m2": 1000, "cycles_per_year": 1,
        "initial_capex_krw": equipment["initial_capex_krw"] + other,
        "horizon_years": 10, "discount_rate": .04, "mode": "new", "replacements_krw": {},
        "scenarios": [
            {"name": "불리", "yield_multiplier": .9, "price_multiplier": .8, "cash_cost_multiplier": 1.1},
            {"name": "기준", "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1},
            {"name": "유리", "yield_multiplier": 1.1, "price_multiplier": 1.2, "cash_cost_multiplier": .9},
        ],
        "reference": {"crop": "딸기", "source_category": row.crop_original, "region": "전국", "year": 2024,
                      "planned_year": 2027, "source_url": row.source_url, "source_page": int(row.source_page),
                      "yield_mode": "실험 모델", "model_prediction": prediction},
        "capital_cost_basis": {"equipment": equipment, "other_capex_krw": other,
                               "total_initial_capex_krw": equipment["initial_capex_krw"] + other},
    }
    results = evaluate_plan(payload)
    sensitivity = simulate_plan(payload, {"yield": .1, "price": .2, "cash_cost": .1}, scenario_index=1)
    assumptions = [
        "실제 농가 사업계획·견적이 아닌 기능 시연 예시",
        "전국 시설딸기(수경) 조사 기준. 2027년 쿼리도 과거 중앙값을 사용하며 연도별 성장효과를 학습한 값이 아님",
        "장비 가격은 공개 등록 표준가격. 설치5백만원·추가 부가세2,957,300원·기타 투자8천만원은 명시적 가정",
        "추가 부가세는 장비와 설치비가 세전이라는 예시 가정의 10%. 실제 세법 적용·공제·환급 여부 미반영",
        "기타8천만원은 장비/설치비와 중복 없는 온실·토목·기타 투자 가정. 정부75,000원/㎡ 기준은 사용하지 않음",
        "10년 동안 같은 연간 조건 유지, 교체비0 가정. 실제 장비 수명이나 유지보수 보장이 아님",
        "기준단가·운영비·감가상각·자가노동은2024년 조사값. 미래가격/비용 상승률 자동반영 없음",
        "초기투자비 회수는 가족노동 기회비용 차감 전 현금흐름. 세금·금융조달·보조금·운전자금·처분가치 제외",
        "장비 설치에 따른 생산성 증가 가정 없음. 가격전망은 별도 도매가격 실험으로 농가수취가격 자동대체 없음",
    ]
    sources = ["data/processed/rda_crop_income.csv", "data/processed/equipment_catalog.json",
               "artifacts/rda_0.pkl", "src/economics.py", "src/risk_simulation.py", "src/equipment_costs.py",
               "src/smartfarm_model.py", "scripts/run_planning_demo.py"]
    return {"inputs": payload, "results": results, "sensitivity": sensitivity,
            "assumptions": assumptions, "source_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}


if __name__ == "__main__":
    result = build_example()
    output = ROOT / "artifacts/planning_demo.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"initial_capex_krw": result["inputs"]["initial_capex_krw"],
                      "prediction": result["inputs"]["reference"]["model_prediction"],
                      "scenarios": [{key: row[key] for key in ["name", "annual_yield_kg", "annual_revenue_krw",
                         "annual_income_before_family_labor_krw", "annual_income_after_family_labor_krw", "npv_krw", "payback_year"]}
                         for row in result["results"]["scenarios"]]}, ensure_ascii=False))
