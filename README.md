# 스마트팜 도입 전 판단 도우미

**대상 시설의 출하량 예측에 그 시설의 판매계획·비용 예산·투자 견적을 연결하는 연구용 프로젝트입니다. 실제 농가의 경제성 정확도와 설비 효과는 아직 검증하지 못했습니다.**

2026-10-18 정정: 기존 설명은 같은 농가의 생산·판매·전체 비용·투자비를 모두 연결한 것처럼 읽힐 수 있었습니다. 실제로는 공개 농가자료의 예측값에 RDA 품목·지역 평균과 가격·설치비 가정을 붙인 계산이었습니다. **외부 평균은 대상 시설의 실측값이 아닙니다.** 현재 계산 경로는 근거를 대상 시설·면적·품종·지역·시설유형·작기·연간 기간에 묶고 기록·견적·예산·외부 참고값을 구분합니다.

[시설별 계산 수정](reports/farm_economics_repair_20261018.md) · [실제 연결 감사](reports/farm_economics_evidence.md) · [추가 공개자료 확인](reports/farm_economics_public_access_20261018.md) · [DSZ 집계기간 수정](reports/dsz_period_gate_repair_20261018.md) · [현재 데이터 흐름](DATA_FLOW.md)

## 현재 확인된 범위

| 항목 | 확인한 내용 | 한계 |
|---|---|---|
| 기존 공개·회원 제공 자료 모델 | 딸기 출하량 76작기·61시설, 별도 5품목 매출 189작기·143시설 | DSZ 성능이 아님. 이번 수정에서 새 실제 모델 학습 없음 |
| API 출하·비용 연결 | 출하 2,823행·161작기, 비용 99행·7작기 중 2작기만 겹침 | 토마토·방울토마토 각 1작기로 비용도 각 1행. 딸기 교집합과 전체 비용 확인 작기는 0 |
| 시설별 경제성 | 대상 시설의 판매배분·비용 9항목·투자·교체·기존 유지안 검사 | 입력에 따른 전망이며 실제 수익 검증은 미완료 |
| DSZ 실행 코드 | 원행별 집계기간·정책·해시 확인 후 적격 자료만 학습 | 실제 미개방 원자료는 로컬 0행 |
| 합성 실행 | 40시설·80작기로 준비·학습·예측 경로 확인 | 합성 점수는 실제 정확도가 아님 |
| DSZ 환경·생육·기상류 | 컬럼·타입·키 검사와 목록 작성 | 모델 입력이나 비용 자료로 사용하지 않음 |

기존 모델의 평가·표본 차이는 [모델 결과](MODEL_RESULTS.md), [계획 모델 검증](reports/planning_connection_validation.md)에 있습니다. 현재의 기간·근거 조건이 이전 연결 설명보다 우선합니다.

## 시설별 계산

Streamlit의 **도입 전 계산 → 내 시설 계획으로 계산**, 정적 웹의 **facility-plan.html**이 수정 경로입니다. 판매기간·판로·등급별 배분율·수취단가, 연간 또는 kg당 비용, 투자·교체 근거를 같은 대상에 연결합니다. 외부 평균을 기본값으로 자동 입력하지 않으며, 미입력 비용은 0원이 아닙니다. 대상 조건이 바뀌면 근거를 다시 확인합니다.

신규 시설은 전체 계획 현금흐름, 개량은 같은 시설의 유지안 대비 추가 현금흐름을 계산합니다. 학습 농가와 새 계획 대상이 같다는 뜻은 아닙니다. 입력한 문서의 진위와 장비 생산성 효과를 자동 인증하지 않습니다. 작기 예측은 기간 근거와 비용 적용 범위 확인 없이 연간 경제성으로 넘기지 않습니다.

**운영 웹사이트에는 이번 수정이 아직 배포되지 않았습니다.** [기존 운영 웹사이트](https://smartfarm-adoption.vercel.app)는 이전 버전입니다. 현재 수정 내용은 이 소스와 [웹 실행 안내](web/README.md)를 기준으로 확인하세요.

## 명세서 기반 CPU 데모

Python 3.12를 사용합니다. 공개 소스에는 설치용 wheelhouse가 없으므로 먼저 의존 패키지를 설치합니다. 설치에는 인터넷 또는 별도 준비한 패키지가 필요합니다. 실행에는 API 키·GPU·LimiX 가중치가 필요 없습니다.

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dsz-cpu.txt
.\run_dsz.ps1 -Demo -Python .\.venv\Scripts\python.exe -UseExistingEnvironment
~~~

PowerShell 없이 실행할 때:

~~~bash
python scripts/prepare_dsz.py --input-dir data/examples/dsz/input --output-dir runs/demo/prepared --period-confirmation data/examples/dsz/input/period_confirmation.json
python scripts/train_dsz.py --data-dir runs/demo/prepared --output-dir runs/demo/models
python scripts/predict_dsz.py --artifact-dir runs/demo/models --plans data/examples/dsz/example_plans.csv --output runs/demo/predictions.csv
~~~

동봉된 기간 확인 JSON도 합성 예제의 가상 근거이며 실제 자료의 확인 문서로 재사용하지 않습니다. 준비·모델·예측 결과에는 검사·제외 사유, 단위·정책·출처 해시가 남습니다.

실제 입력은 DZ_002 시설과 DZ_004 경영조사가 필수입니다. 학습에는 **정의 근거 문서와 해시, 원본 해시, 집계 정책, 원행→시설·작기 매핑, 행별 집계 시작·종료일**을 담은 확인 JSON도 필요합니다. 근거가 없으면 감사 후보만 생성하고 학습은 차단합니다. 조사일이 작기 안에 있다는 사실이나 연 1작기 동의만으로 통과하지 않습니다.

~~~powershell
.\run_dsz.ps1 -InputDir D:\approved_data -Plans D:\plans.csv -PeriodConfirmation D:\period_confirmation.json -ManagementPolicy single_record_per_cycle -Python .\.venv\Scripts\python.exe -UseExistingEnvironment
~~~

DSZ 사전 입력은 **품목·지역·단동/연동·온실 규모 설명·면적·시작 연도·시작 월의 7개**입니다. 실제 종료일·환경·생육·기상 관측값은 포함하지 않습니다. 일부 기간만 확인됐다면 확인된 적격 행만 학습하며 사용·제외 내역을 보존합니다.

[현장 실행 안내](reports/dsz_onsite_guide.md) · [입력·확인 JSON 계약](reports/dsz_schema_contract.md) · [모델 방법](reports/dsz_model_method.md) · [명세 반영 범위](reports/dsz_spec_usage.md)

## 검증과 공개 범위

2026-10-18 공개 소스 검사: **Python 291개 통과·4개 건너뜀·하위 검사 72개 통과**, 웹 **28개 통과·1개 건너뜀**, 정적 빌드 **27개 파일 생성**. Python의 건너뛴 검사는 미포함 로컬 자료가 필요하며, 원자료 기반 앱 검사는 기존 설정대로 기본 검사에서 제외했습니다. 웹의 건너뛴 검사는 로컬 Python 환경을 요구하는 Python/JavaScript 비교입니다.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
npm run test:web
npm run build
~~~

이 결과는 소프트웨어·합성자료 검사이며 실제 농가 경제성 검증이 아닙니다. 수정 당시 로컬 검사는 각 수정 보고서에 별도로 기록했습니다.

실제 농가 원행·식별자 목록·개별 예측·인증 정보·문의 초안은 공개하지 않습니다. 약 245MB 오프라인 ZIP은 로컬 검증 산출물이며 공개 다운로드가 아닙니다. 전체 Streamlit 연구 화면에는 별도 원자료·산출물이 필요합니다. [저장소 데이터 범위](DATA_SCOPE.md)

## 이전 발표자료와 이미지

**아래는 2026-10-18 수정 이전 산출물입니다. 현재 자료 연결·기간 확인 규칙은 위 수정 보고서와 DATA_FLOW.md로 대체합니다. 경제성 실증 완료의 근거로 사용하지 않습니다.** 이미지·PPT 원본은 수정하지 않았습니다.

<details>
<summary>이전 발표자료·그림 펼치기 — 현재 설명으로 대체됨</summary>

[쉬운 PPT](presentation/smartfarm_easy.pptx) · [쉬운 PDF](presentation/smartfarm_easy.pdf) · [상세 PPT](presentation/smartfarm_proposal.pptx) · [상세 PDF](presentation/smartfarm_proposal.pdf)

[명세 반영 그림](assets/diagrams/dsz-spec-usage-easy.png) · [세로 그림](assets/diagrams/dsz-spec-usage-portrait.png) · [명세 슬라이드](assets/diagrams/dsz-spec-usage.png) · [작기 연결](assets/diagrams/dsz-cycle-join.png) · [경제성 연결](assets/diagrams/dsz-economic-link.png) · [기술 흐름](assets/diagrams/dsz-data-flow.png)

[서비스 흐름](assets/diagrams/easy-service-flow.png) · [자료 구성](assets/diagrams/easy-data-sources.png) · [로컬 모델 그림](assets/diagrams/local-model-flow.md) · [실제자료 흐름](assets/diagrams/actual-data-flow.png) · [대시보드 화면](assets/dashboard/)

[이전 계산 시연](reports/planning_demo_summary.json)은 공개 집계 평균과 명시적 가정의 예시이며 동일 농가 경제성 검증이 아닙니다.

</details>
