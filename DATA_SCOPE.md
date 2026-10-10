# 저장소 데이터 범위

포함된 CSV는 `data/examples/dsz/input/`과 `example_plans.csv`의 **합성 예제**뿐입니다. 시설ID는 `SYN_FARM_` 접두사를 사용합니다. 원본 생성 코드는 `generate_fixture.py`이며, 예제에 실제 농가 분포를 재현했다는 주장을 하지 않습니다.

`data/raw/dsz/`의 TXT·ZIP은 사용자가 제공한 대회 **데이터 정의서**입니다. 실제 농가 기록이 아닙니다. TXT의 해시는 입력 스키마와 대조하므로 원문을 임의로 수정하지 않습니다.

실제 농가·API 응답·학습 모델·행별 예측, API 키·회원 인증 정보, 설치용 wheel·가상환경·GPU 가중치는 포함하지 않습니다. 요약 점수와 설명은 `MODEL_RESULTS.md`와 아래 공개 결과 파일로 보존합니다. 기관별 자료와 모델의 이용 조건은 각각 확인해야 하며, 이 저장소가 외부 자료의 재배포 권한을 부여하지 않습니다.

## 추가 공개한 가격·시연 요약

- `data/processed/equipment_catalog.json`: 스마트팜코리아 등록 장비 3종의 공개 묶음 가격·옵션. 농가 설비 이력이나 계약 기록이 아닙니다. `data/processed/`에서 이 파일만 Git 추적 예외입니다.
- `reports/equipment_source_check_2026-10-10.json`: 해당 3종의 확인일·조회 방법·공개 가격표. 개인 농가나 회사 담당자 연락처는 포함하지 않습니다.
- `reports/price_forecast_metrics_summary.json`: 574개 월 가격 관측의 집계 검증 결과·시간 분리·입출력 해시. 월별 원가격이나 행별 예측은 포함하지 않습니다.
- `reports/planning_demo_summary.json`: 공개 집계 기준값과 사용자 가정을 조합한 딸기 1,000㎡ 시연 결과. 개별 농가 기록이 아니며 2,000개 민감도 샘플 원행은 제외했습니다.
- `reports/inseason_metrics_summary.json`: 40개 방문 쌍·21시설의 초장 예측 집계 성능과 각 10개 쌍을 묶은 4개 구간 평균. 시설ID·조사일별 입력·개별 예측은 포함하지 않습니다.
- `reports/planning_reference_scenarios.json`: 보관된 공개 월 도매가격 5개월과 그 상대 변화·기상청 평년값·사용자 연간 영향 가정으로 계산한 조건별 예시. 개인 농가 기록이 아닙니다.
- `presentation/smartfarm_proposal.pptx`, `assets/dashboard/`: 같은 집계 결과·명시적 시연 가정을 설명하는 발표자료와 화면 이미지입니다.

설치비·부가세 포함 여부, 장비 간 호환성·적용 면적·수명·생산성 효과는 이 가격 자료로 확정할 수 없습니다. 장비비 계산을 모델 학습용 농가별 설비 데이터 확보로 해석하지 않습니다.

## 출처

- [농촌진흥청 ADP 현장 자료](https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE)
- [스마트팜코리아](https://www.smartfarmkorea.net/): 작기별 API 및 큐레이션 데이터
- [농사로 2024 소득자료](https://www.nongsaro.go.kr/portal/ps/pst/pstb/pstbc/mngmtDtaDtl.ps?nttSn=842)
- [KAMIS 월별 가격](https://www.kamis.or.kr/customer/price/wholesale/period.do)
- [기상청 기후평년값](https://data.kma.go.kr/normals/info1.do)
- [농림축산식품부 온실 사업지침](https://www.mafra.go.kr/bbs/home/791/577560/artclView.do)
- [스마트팜코리아 공개 장비 소개](https://www.smartfarmkorea.net/company/equipmentInfo.do)
- [데이터안심구역 공모전](https://dsz.kdata.or.kr/contest/introduce/participate.do#evaluation)

농사로 수집 자료의 게시물상 조건은 공공누리 제2유형(출처표시·상업적 이용금지)입니다. LimiX 가중치는 StableAI LimiX Non-Commercial License v1.0을 따릅니다. 원자료와 가중치는 동봉하지 않았습니다.

## 기존 Streamlit 화면을 실행하려면

`requirements.txt`를 설치하고 별도로 확보·정규화·학습한 다음 파일이 필요합니다.

```text
data/processed/rda_crop_income.csv
data/processed/capex_reference.csv
data/processed/kamis_wholesale_monthly_kg.csv
artifacts/model_metrics.json
artifacts/holdout_predictions.csv
data/processed/equipment_catalog.json  # 저장소에 포함한 공개가격 예외
```

실험 모델 선택에는 `scripts/train_initial.py`가 만든 추가 모델 파일이 필요합니다. 실제 LimiX·API·큐레이션 결과 표시에도 해당 로컬 입력·출처·해시·산출물이 필요합니다. 선택 결과가 없다고 합성 점수를 대신 표시하지 않습니다.

가격 실험 화면은 해당 로컬 가격 파일로 `python scripts/run_price_forecast.py`를 실행하면 `artifacts/price_forecast_metrics.json`과 검증·전망 CSV 3개를 만듭니다. 화면은 입력·코드·출력 해시가 일치하는 결과만 현재 결과로 표시합니다. `python scripts/run_planning_demo.py`도 로컬 RDA 집계 파일과 `artifacts/rda_0.pkl`이 필요합니다. 저장소의 집계 요약 JSON을 원자료나 학습 모델 대신 자동 사용하는 방식은 아닙니다.

재배 중 실험은 별도로 확보한 `strawberry_curation_growth.csv`, `strawberry_curation_environment.csv`와 원문 정의서가 필요합니다. `python scripts/run_inseason_model.py`가 집계 결과와 로컬 감사용 `artifacts/inseason_oof_private.csv`를 만듭니다. **해당 개별 예측 CSV는 공개하지 않습니다.** 생육·환경 관측은 도입 전 계획 입력과 구분합니다.

가격·기후를 계획 가정에 연결하는 `python scripts/run_reference_scenarios.py`는 기존 가격 실험 산출물·기후평년값과 계획 시연에 필요한 로컬 입력을 요구합니다. 2026 가격 전망의 상대 변화 전달은 사용자 선택이며, 날씨 영향률은 사용자가 입력한 연간 효과입니다. 최신 기상예보나 검증된 농가 수취가격 전환식이 아닙니다.

전체 준비 후 `run_app.ps1` 또는 `python -m streamlit run app.py`를 사용합니다. 새로 복제한 저장소만으로 바로 재현 가능한 경로는 README의 **DSZ 합성 CPU 데모**입니다.
