# 안심구역: 딸기 스마트팜 재배 중 출하량 예측

명세서의 실제 표에서 **같은 시설·같은 작기의 예측 시점 이전 관측**을 연결하는 코드입니다. 현재 확인한 것은 합성 자료의 실행·연결·누수 방지입니다. 실제 대회 원자료의 연결률이나 예측 정확도 검증은 별도로 필요합니다.

| 경로 | 입력 | 목표 |
|---|---|---|
| 기존 `run_dsz.ps1` | 품목·지역·단동/연동·온실규모·면적·시작연도·시작월 | 확인된 작기 총출하량과 총수입의 별도 모델 |
| 추가 `run_dsz.ps1 -InSeason` | 같은 7개 + 예측일까지의 환경·생육·기상 | 딸기 작기 전체 총출하량 kg |

한 실행에 고정 경과일 하나를 사용합니다. 30일 모델과 60일 모델은 각각 학습합니다. 결과는 오늘 이후 남은 출하량이나 장비 설치 효과가 아닙니다.

## 합성 실행

Python 3.12와 `requirements-dsz-cpu.txt`의 CPU 패키지를 준비한 뒤 프로젝트 폴더에서 실행합니다. 인터넷이 없는 환경에는 설치 완료 환경이나 사전에 준비한 wheelhouse가 필요합니다.

```powershell
.\run_dsz.ps1 -Demo -InSeason -CutoffDays 30 `
  -Python .\.venv\Scripts\python.exe -UseExistingEnvironment
```

합성 예제는 기존 40시설·80작기 중 딸기 16작기의 관측과 별도의 미학습 가상 시설을 포함합니다. 관측은 출하량 정답에 맞춰 생성하지 않았습니다. 합성 점수는 실제 성능이 아닙니다.

## 실제 파일 배치

CSV 또는 단일 시트 XLSX를 사용하며 명세서의 영문 열 이름을 보존합니다. `DZ_001` 같은 별칭과 명세서의 영문 테이블명 모두 지원합니다.

| 표 | 사용 |
|---|---|
| DZ_002 시설 | 시설ID·작기일련번호·기간·품목·지역·온실·면적 |
| DZ_004 경영조사 | 학습용 실제 총출하량과 집계기간 근거 |
| DZ_001 환경 | 내부/외부 온도·습도·CO₂: 최근 구간 평균·최저·최고, 최근 7일 평균 |
| DZ_003 생육 | 초장·관부직경·착과: 최근 방문 표본평균·이전 방문 대비 변화, 최근 생육주수 |
| DZ_005 기상 | 시설에 연결된 관측소의 일별 온도·풍속·이슬점 요약 |
| DZ_006 기상특보 | 예측일까지 발표된 원문 행 수. 사건 수나 피해 여부가 아님 |
| DZ_007 태풍 | 검사·목록만. 관측일만으로 예보 발표시점을 확정할 수 없어 모델 입력 제외 |

기존 7개에 관측 수치 27개와 관측 기록 수·경과일 등의 상태 8개를 추가합니다. 총 42개 입력 후보이며, 유효한 환경·생육·기상 수치가 연결된 행만 확장 모델에 사용합니다. 추가 입력이 많다고 실제 정확도가 보장되지는 않습니다.

```powershell
.\run_dsz.ps1 -InSeason `
  -InputDir D:\approved_data\history `
  -PeriodConfirmation D:\approved_data\period_confirmation.json `
  -QueryInputDir D:\approved_data\current `
  -Requests D:\approved_data\requests.csv `
  -CutoffDays 30 -WindowDays 28 -Crop 딸기 `
  -Python .\.venv\Scripts\python.exe -UseExistingEnvironment
```

`requests.csv`는 다음 세 열만 사용합니다. 시설ID는 `FCLT_ID`, 작기ID는 `FRMTM_SNO`에 대응합니다.

```csv
plan_id,facility_id,cycle_id
my_plan,FACILITY_001,1001
```

예측용 `current` 폴더에는 시설표와 관측표가 필요하며 경영조사 정답은 필요 없습니다. 현재 작기의 종료일은 비워 둘 수 있습니다. `QueryInputDir`를 생략하면 학습 입력 폴더를 사용합니다. 학습한 시설의 재예측은 미학습 시설 성능 검증이 아닙니다.

## Python만 사용하는 실행 명령

다음은 합성 예제 명령입니다. 실제 실행에서는 입력 경로와 기간 확인 JSON을 바꿉니다. 출력 폴더는 매번 새 경로를 사용합니다.

```bash
python scripts/prepare_dsz.py --input-dir data/examples/dsz_inseason/input --output-dir runs/inseason_demo/prepared --period-confirmation data/examples/dsz_inseason/input/period_confirmation.json
python scripts/run_dsz_inseason.py train --data-dir runs/inseason_demo/prepared --input-dir data/examples/dsz_inseason/input --output-dir runs/inseason_demo/models --cutoff-days 30
python scripts/run_dsz_inseason.py predict --artifact-dir runs/inseason_demo/models --input-dir data/examples/dsz_inseason/query --requests data/examples/dsz_inseason/requests.csv --output runs/inseason_demo/predictions.csv
```

## 결과 파일

- `models/dsz_inseason_metrics.json`: 연결된 작기·시설 수, 기본/확장 모델 비교, 시설별 분할, 다음 연도 검사·제외 사유, 입력·코드 해시.
- `models/dsz_inseason_oof.csv`: 같은 시설이 학습·검증에 겹치지 않게 만든 검증 예측.
- `models/dsz_inseason_training_rows.csv`: 실제 학습에 사용한 시설·작기와 관측 요약.
- `models/observation_audit.json`, `observation_validation.csv`: 연결·관측 제외 사유와 명세 검사 결과.
- `models/dsz_inseason_shipment.joblib`: 해당 실행에서 만든 로컬 모델. 외부의 미확인 pickle/joblib 파일을 불러오지 않습니다.
- `predictions.csv`, `predictions.provenance.json`: 요청 시설의 출하량 kg와 예측시점·범위·출처.

## 연결·검증 원칙

- 조사일만으로 출하량 집계기간을 확정하지 않습니다. 기존 기간 확인 JSON에 실제 정의 근거·파일 해시·원행과 작기별 기간을 기록해야 학습됩니다. 합성 선언을 실제 자료에 복사하면 안 됩니다.
- 원 시설표 전체에서 중복·겹친 작기·잘못된 기간을 확인합니다. 표별 관측을 각각 요약한 뒤 일대일로 연결합니다.
- 예측시각은 시작일 00:00 + `CutoffDays`입니다. 환경은 그 시각까지의 측정, 날짜만 있는 생육·기상은 해당 날짜가 끝난 뒤부터 사용합니다. 특보는 발표시각 기준입니다.
- 기본 최근 구간은 28일입니다. 여러 식물은 방문일별 표본평균으로 합치며, 평균 변화가 같은 개체의 성장을 뜻하지는 않습니다.
- 관측시각과 실제 정보 제공시각은 다를 수 있습니다. 제공 지연·소급 수정까지 확인한 실시간 검증은 별도로 필요합니다. 적재일시·적재사용자ID는 생산성 입력에 넣지 않습니다.
- 누락 수치를 0으로 대입하지 않고, 결측 처리는 학습 분할에서만 학습합니다. 관측 연결이 없는 요청은 조용히 기본 모델로 대체하지 않습니다.
- 기본 7개와 확장 입력은 동일한 시설·작기·분할에서 중앙값·CatBoost·XGBoost를 비교합니다. 모델 선택에 사용한 점수는 독립 최종 성능이 아닙니다. 다음 연도 검사는 이전에 완료된 작기와 미학습 시설 조건을 만족할 때만 수행합니다.
- 시설ID·작기ID는 연결·분할용이고, 총수입·총출하량·최종 종료일은 예측 입력에서 제외합니다. 환경·생육 행 수가 늘어도 독립적인 학습 시설 수가 늘어나는 것은 아닙니다.
- 공개자료 농가ID와 대회 시설ID는 자동 연결하지 않습니다.

## 경제성과의 관계

기존 시설별 경제성 계산은 유지합니다. 같은 대상 시설의 판매계획·운영비·설치 견적·연간 기간이 별도로 필요하며, 재배 중 예측은 `inseason_cycle_total` 범위로 표시해 기존 재배 전 경제성 경로에 자동 연결하지 않습니다. 출하량 예측만으로 설비 도입 효과나 투자 회수 정확도를 검증하지 않습니다.

GitHub와 소스 패키지에는 코드·명세서·합성 예제만 포함합니다. 원자료·행별 예측·학습 모델은 안심구역의 승인된 사용·반출 범위를 따릅니다.
