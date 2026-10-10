"""Run actual strawberry environment/growth pilot; publish aggregates only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.inseason_model import (ENVIRONMENT, ENVIRONMENT_FEATURES, FEATURES,  # noqa: E402
                               GROWTH_FEATURES, TARGET, build_cohort, evaluate)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    growth_path = ROOT / "data/processed/strawberry_curation_growth.csv"
    environment_path = ROOT / "data/processed/strawberry_curation_environment.csv"
    growth = pd.read_csv(growth_path)
    environment = pd.read_csv(environment_path)
    cohort, audit = build_cohort(growth, environment)
    models, oof = evaluate(cohort)
    output_path = ROOT / "artifacts/inseason_oof_private.csv"
    output_path.parent.mkdir(exist_ok=True)
    oof.to_csv(output_path, index=False, encoding="utf-8-sig")
    best = min(models, key=lambda row: row["mae_mm"])["model"]
    limitations = [
        "정확히 7일 간격으로 관측된 방문 쌍만 평가한 소규모 후향 실험이다. 불규칙 방문 농가 전체를 대표하지 않는다.",
        "같은 개체의 연속 성장량이 아닌 시설·방문별 관측 표본 평균 초장(mm)을 예측한다. 표본 구성이 달라질 수 있다.",
        "환경 분석일자를 관측일의 대리값으로 사용했다. 실제 과거 수신 시각/지연은 없어 실시간 가용성을 입증하지 않는다.",
        "온도·습도의 7/28일 최소·최대는 기간 내 일평균 값의 최소·최대이며 순간 최저·최고 온도가 아니다. CO₂는 분석일자별 농도 기록을 요약하며 원본의 하루 내 집계 방식은 명시되지 않았다.",
        "일사량·외부온도·기상특보·태풍은 이 큐레이션 원본에 없어 누적 일사량, GDD 및 기상 예측은 만들지 않았다.",
        "mm 원문 값을 유지하고 의심 값의 임의 단위 환산이나 이상치 제거를 하지 않았다.",
        "시설 분리 교차검증은 미래 연도 검증이 아니다. 모델 선택과 성능 보고에 같은 OOF 평가를 사용해 별도 외부검증이 필요하다.",
        "운영 중 보조 실험이며 도입 전 수확량·투자수익 모델에는 관측 환경/생육 값을 넣지 않는다.",
    ]
    # Paired examples are deliberately aggregate bins, not masked individual records.
    ordered = oof.sort_values("height_mm").reset_index(drop=True)
    ordered["group"] = pd.cut(ordered.index, bins=4, labels=False)
    examples = []
    for number, part in ordered.groupby("group"):
        examples.append({"group": int(number) + 1, "pairs": len(part),
                         "current_height_mm_mean": float(part["height_mm"].mean()),
                         "observed_next_height_mm_mean": float(part[TARGET].mean()),
                         "predicted_next_height_mm_mean": float(part[best].mean())})
    source_paths = [growth_path, environment_path,
                    ROOT / "data/raw/smartfarm_curation_docs/Strawberry_Growth_Env_Shipping_Definition.hwp",
                    ROOT / "src/inseason_model.py", Path(__file__)]
    result = {
        "study": "strawberry_observed_visit_height_7d", "status": "actual_data_pilot_completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": "7일 뒤 시설·방문 관측 표본 평균 초장", "target_unit": "mm",
        "source_counts": audit, "cohort": {"pairs": len(cohort), "facilities": audit["facilities"],
                                         "horizon_days": 7, "folds": min(5, audit["facilities"])},
        "feature_groups": {"growth": GROWTH_FEATURES, "prior_environment": ENVIRONMENT_FEATURES},
        "environment_units": {name: unit for name, unit in ENVIRONMENT.values()},
        "feature_count": len(FEATURES), "models": models, "best_model": best,
        "illustrative_holdout_examples": examples, "limitations": limitations,
        "source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
                          for path in source_paths},
        "private_oof_sha256": sha256(output_path),
        "private_oof_rows_not_published": True,
    }
    metrics_path = ROOT / "artifacts/inseason_metrics.json"
    metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 운영 중 딸기 생육 점검: 실제 환경·생육 연결 실험", "",
             f"생육 {len(growth):,}행 중 초장 mm 원행 {audit['height_raw_rows_mm']}개를 확인했다. "
             f"환경은 {len(environment):,}행이다. 시설·방문별 평균을 만들고 유일한 작기에 연결한 뒤 "
             f"정확히 7일 간격의 {len(cohort)}쌍·{audit['facilities']}시설을 평가했다.", "",
             "결합: 시설 ID와 환경 원본의 정식 시작·종료 기간이 방문일을 유일하게 포함해야 한다. "
             "현재와 다음 방문은 같은 작기여야 하며 표본 단위 중복 충돌은 제외한다. "
             "환경은 현재 방문일보다 엄격히 앞선 7/28일만 사용한다. 같은 날 일집계와 미래 관측은 제외한다.", "",
             "입력: 현재 초장·엽수·엽장·엽폭·관부직경, 달력 일차·정식 후 일수, 이전 방문과의 간격·평균 초장 변화, "
             "직전 7/28일 내부 일평균 온도·평균습도와 분석일자별 CO₂ 농도의 평균/최소/최대/유효 관측일수. "
             "온도·습도는 기존 일평균을, CO₂는 분석일자별 기록을 요약한다. CO₂의 하루 내 집계 방식은 원본에 명시되지 않았다. "
             "결측 날짜를 정상값으로 채우지 않는다.", "",
             "예측 기준 시점은 현재 생육 조사 직후다. 다음 조사에서 관측될 시설 평균 초장(mm)을 "
             "예측하며, 개별 식물 성장량이나 수확량으로 해석하지 않는다.", "",
             "검증: 같은 시설은 언제나 같은 fold에 두는 5-fold GroupKFold. "
             "CatBoost/XGBoost는 120 trees/depth 2, 학습률 0.05 고정값을 사용하며 검증 결과로 튜닝하지 않았다. "
             "현재 초장을 유지하는 기준선, 생육만 사용하는 CatBoost, 환경을 추가한 CatBoost/XGBoost를 같은 쌍에서 비교했다.", "",
             "|모델|MAE(mm)|RMSE(mm)|", "|---|---:|---:|"]
    lines += [f"|{row['model']}|{row['mae_mm']:.2f}|{row['rmse_mm']:.2f}|" for row in models]
    lines += ["", f"OOF 최저 MAE: `{best}`. 결과는 파일의 원값에 대한 소규모 비교이며 성능 보장은 아니다.", "",
              "## 해석 제한", ""] + [f"- {value}" for value in limitations]
    lines += ["", "## 재현과 공개 범위", "",
              "`.venv/Scripts/python.exe -X utf8 scripts/run_inseason_model.py`", "",
              "`artifacts/inseason_metrics.json`은 집계 성능·출처/코드 SHA256·4개 초장 구간 평균을 포함한다. "
              "`artifacts/inseason_oof_private.csv`는 시설/날짜별 입력과 OOF 예측을 보존하는 로컬 감사 자료이며 GitHub에 올리지 않는다. "
              "집계 예시는 전체 40쌍을 현재 초장 순 4구간으로 나눴으며 좋은 사례만 고르지 않았다."]
    (ROOT / "reports/inseason_model_notes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"cohort": result["cohort"], "models": models, "best_model": best}, ensure_ascii=False))


if __name__ == "__main__":
    main()
