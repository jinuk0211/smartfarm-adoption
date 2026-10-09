# 저장소 데이터 범위

포함된 CSV는 `data/examples/dsz/input/`과 `example_plans.csv`의 **합성 예제**뿐입니다. 시설ID는 `SYN_FARM_` 접두사를 사용합니다. 원본 생성 코드는 `generate_fixture.py`이며, 예제에 실제 농가 분포를 재현했다는 주장을 하지 않습니다.

`data/raw/dsz/`의 TXT·ZIP은 사용자가 제공한 대회 **데이터 정의서**입니다. 실제 농가 기록이 아닙니다. TXT의 해시는 입력 스키마와 대조하므로 원문을 임의로 수정하지 않습니다.

실제 농가·API 응답·학습 모델·행별 예측, API 키·회원 인증 정보, 설치용 wheel·가상환경·GPU 가중치는 포함하지 않습니다. 요약 점수만 `MODEL_RESULTS.md`로 보존합니다. 기관별 자료와 모델의 이용 조건은 각각 확인해야 하며, 이 저장소가 외부 자료의 재배포 권한을 부여하지 않습니다.

## 출처

- [농촌진흥청 ADP 현장 자료](https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE)
- [스마트팜코리아](https://www.smartfarmkorea.net/): 작기별 API 및 큐레이션 데이터
- [농사로 2024 소득자료](https://www.nongsaro.go.kr/portal/ps/pst/pstb/pstbc/mngmtDtaDtl.ps?nttSn=842)
- [KAMIS 월별 가격](https://www.kamis.or.kr/customer/price/wholesale/period.do)
- [기상청 기후평년값](https://data.kma.go.kr/normals/info1.do)
- [농림축산식품부 온실 사업지침](https://www.mafra.go.kr/bbs/home/791/577560/artclView.do)
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
```

실험 모델 선택에는 `scripts/train_initial.py`가 만든 추가 모델 파일이 필요합니다. 실제 LimiX·API·큐레이션 결과 표시에도 해당 로컬 입력·출처·해시·산출물이 필요합니다. 선택 결과가 없다고 합성 점수를 대신 표시하지 않습니다.

전체 준비 후 `run_app.ps1` 또는 `python -m streamlit run app.py`를 사용합니다. 새로 복제한 저장소만으로 바로 재현 가능한 경로는 README의 **DSZ 합성 CPU 데모**입니다.
