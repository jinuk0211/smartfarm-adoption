# DSZ 명세 기반 오프라인 모델 실행법

이 경로는 미개방 원자료의 명세에 맞춰 준비한 코드를 현장에서 실제 파일로 실행하기 위한 것이다. `synthetic_schema_fixture`는 **코드 실행을 확인하는 가상 자료**이며, 점수·예측은 실제 농가 성능을 뜻하지 않는다. 실제 자료는 준비 단계에서 `onsite_private_unverified`로 구별하며 집계 가정이 확인되기 전에는 인증된 작기 총량이라고 표현하지 않는다.

## 입력과 타깃

`prepare_dsz.py`가 생성하는 `dsz_model_candidates.csv`와 `dsz_manifest.json`을 입력한다. 모델은 CSV의 SHA, 출처 태그, 특성 계약을 검사한다. 정확히 다음 7개 계획 특성만 사용한다.

`crop, region, greenhouse_type, greenhouse_size, area_m2, planned_start_year, planned_start_month`

면적은 ㎡이며 양수여야 한다. 실제 종료일, 관측 환경·생육, 경영 수치, 시설ID, 작기ID는 입력하지 않는다. 시설ID는 검증 분리에만 사용한다. 출하량 kg와 총수입 원은 각각 유효한 행으로 독립 학습하며, 한쪽 결측 때문에 다른 타깃을 지우지 않는다. 명시적으로 관측된 0은 보존하고 결측을 0으로 대체하지 않는다.

기본 `single_record_per_cycle`은 정확히 하나의 경영 기록이 작기에 연결된 후보라는 **명시적 가정**이다. 준비 단계에서 다른 집계 정책을 선택하면 `target_assumption`이 모든 모델·OOF·예측으로 전파된다. 어떤 정책도 공급자가 확인한 작기 완결성이나 연간 환산을 자동 보증하지 않는다. 총수입은 순이익이 아니다.

## CPU 비교와 예측

시설 수에 따라 GroupKFold 2~5개를 사용하며, 같은 시설의 작기는 한 폴드에 함께 둔다. 특정 타깃의 시설이 2개 미만이면 그 타깃만 `skipped_insufficient_data`로 기록하며 다른 타깃은 계속 학습한다. 두 타깃 모두 부족할 때는 실패한다. 품목 중앙값, 학습 자료의 품목별 kg/㎡ 또는 원/㎡ 중앙값×계획면적, CatBoost(MAE), XGBoost(absolute error)를 같은 타깃 행·폴드에서 비교한다. 범주 변환과 기준선은 학습 폴드만 사용한다. 학습 정답이 상수(전부 0 포함)이거나 모든 학습 특성이 상수인 폴드는 두 ML 방법을 학습 중앙값으로 대체하고 이유·폴드·방법을 감사 기록에 남긴다. 이 판단에는 검증 정답을 사용하지 않는다. 검증에만 있는 품목은 OOF에서 표시하며, 실제 계획 예측은 학습에 없던 품목을 거부한다.

OOF MAE가 가장 작은 CPU 방법을 전체 유효행에 다시 적합해 로컬 joblib 파일에 저장한다. 선택에 사용한 OOF는 독립된 최종 검증셋이 아니며 미래 연도·장비 도입의 인과 효과·투자회수기간을 검증하지 않는다. 예측기는 우리가 생성한 신뢰할 수 있는 로컬 파일만 대상으로 하고, 불러오기 전에 선언된 SHA를 확인한다. 외부인이 제공한 pickle/joblib을 받아 실행하는 기능이 아니다.

```powershell
python scripts/prepare_dsz.py --input-dir data/examples/dsz/input --output-dir data/examples/dsz/processed
python scripts/train_dsz.py --data-dir data/examples/dsz/processed --output-dir artifacts/dsz_demo
python scripts/predict_dsz.py --artifact-dir artifacts/dsz_demo --plans data/examples/dsz/example_plans.csv --output artifacts/dsz_demo/example_predictions.csv
```

현장에서는 `--data-dir`, `--output-dir`, `--plans`, `--output`을 실제 자료와 현장 결과 폴더로 지정한다. 네트워크·서버·외부 API를 사용하지 않는다. `dsz_model_metrics.json`, 타깃별 OOF, 모델 파일, 실행 보고서에 데이터 종류와 출처가 남는다. 예측 CSV와 `.provenance.json`에도 가상/실제 입력 출처가 전파된다.

## 선택적인 LimiX

기본 CPU 번들은 LimiX 코드·가중치·CUDA가 없어도 동작한다. 사전에 허용된 GPU와 이미 설치·검증한 공식 400M 체크포인트가 있는 전체 작업환경에서만 `--include-limix --limix-python .venv-limix/Scripts/python.exe`로 별도 비교를 실행한다. 코드를 지연 import하고 누락된 환경은 명확히 오류로 처리하며 다운로드하거나 다른 모델로 대체하지 않는다.

이 추가 비교는 동일 시설 폴드·행을 사용하고 실제 V2 회귀 전처리와 내부 정규화의 학습행 불변성을 검사한다. 고정된 사전학습 가중치를 사용하며, 기본 CPU 배포 모델 선택은 바꾸지 않는다. 추가 점수와 OOF는 `dsz_limix_comparison.json`, `dsz_*_limix_oof.csv`에 별도로 저장된다. 가상 자료로 실행한 LimiX 점수 역시 실행 검증에 한정된다.
