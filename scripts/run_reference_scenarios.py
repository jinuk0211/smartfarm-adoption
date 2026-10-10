"""Run traceable market-relative and user weather scenarios on the plan demo."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from scripts.run_planning_demo import build_example  # noqa: E402
from src.economics import evaluate_plan  # noqa: E402
from src.scenario_assumptions import relative_market_price  # noqa: E402


def main() -> None:
    base = build_example()
    old = pd.read_csv(ROOT / "artifacts/price_forecast_holdout_predictions.csv", encoding="utf-8-sig")
    future = pd.read_csv(ROOT / "artifacts/price_forecast_forecast.csv", encoding="utf-8-sig")
    market = relative_market_price(old, future, crop="딸기", variety="설향", grade="상품",
                                   months=[1, 2, 3, 4, 12], method="forecast_krw_per_kg")
    climate = pd.read_csv(ROOT / "data/processed/climate_normals_monthly.csv", encoding="utf-8-sig")
    normal = climate.loc[(climate.station_name == "대구") & (climate.month == 1)].iloc[0]
    weather = {"condition": "저온", "station_id": int(normal.station_id), "station_name": "대구", "month": 1,
               "normal_period": "1991–2020", "normal_mean_temperature_c": float(normal.mean_temperature_c),
               "normal_monthly_precipitation_mm": float(normal.monthly_precipitation_mm),
               "user_yield_change_percent": -10.0, "user_cash_cost_change_percent": 15.0,
               "scope": "annual_total_effect",
               "interpretation": "평년 기후 참고 + 사용자 영향 가정. 미래 기상예보·학습된 영향 아님",
               "source_url": "https://data.kma.go.kr/normals/info1.do"}
    records = []
    for name, price_factor, quantity_factor, cost_factor in [
        ("기존 계획", 1.0, 1.0, 1.0),
        ("도매가격 상대변화 적용 가정", market["factor"], 1.0, 1.0),
        ("상대가격 + 저온 영향 가정", market["factor"], .9, 1.15),
    ]:
        payload = copy.deepcopy(base["inputs"])
        payload["scenarios"] = [{"name": name, "price_multiplier": price_factor, "yield_multiplier": quantity_factor, "cash_cost_multiplier": cost_factor}]
        payload["reference_scenario"] = {"market": market if price_factor != 1 else None,
                                          "weather": weather if cost_factor != 1 else None}
        records.append({"inputs": payload, "results": evaluate_plan(payload)})
    files = ["artifacts/price_forecast_metrics.json", "artifacts/price_forecast_holdout_predictions.csv",
             "artifacts/price_forecast_forecast.csv", "data/processed/climate_normals_monthly.csv",
             "src/scenario_assumptions.py", "scripts/run_reference_scenarios.py"]
    result = {"market_assumption": market, "weather_assumption": weather, "comparisons": records,
              "interpretation": "조건별 계산 연결 시연. 도매-농가 상대변화 전달·날씨 영향 수치는 사용자 가정이며 정확도 검증된 2027년 예측이 아님",
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}}
    (ROOT / "artifacts/planning_reference_scenarios.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"price_factor": market["factor"], "scenarios": [record["results"]["scenarios"][0] for record in records]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
