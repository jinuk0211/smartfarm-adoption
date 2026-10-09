# 농정원 미개방 데이터 — 현장 실행 안내

> 이 안내의 설치 절차는 별도로 만든 **wheelhouse 포함 오프라인 ZIP**을 기준으로 합니다. GitHub 소스에는 wheelhouse가 없습니다. GitHub 사용자는 먼저 `requirements-dsz-cpu.txt`를 설치하고 `run_dsz.ps1 -Demo -Python .\.venv\Scripts\python.exe -UseExistingEnvironment`로 실행하세요. 자세한 시작 명령은 [README](../README.md)를 따릅니다.

사용자가 대구 데이터안심구역을 방문했으며 원자료는 현장에서만 볼 수 있다고 확인했다. 이에 **명세서에 맞춰 실행 코드를 완성하고 현장에서 실제 파일을 넣어 실행하는 방식**으로 준비했다. 동봉한 농가 CSV는 모두 인위적으로 만든 예제다. 실제 미개방 원자료·계정·API 키는 들어 있지 않다.

## 이 패키지가 하는 일

시설·경영조사 파일 검사 → 시설ID와 작기 기간으로 연결 → 출하량과 매출을 각각 시설별 교차검증 → CPU 모델 선택·저장 → 새 계획 조건의 예측 CSV 생성.

- 출하량: 정의서의 `ALL_SHPMNT_KGUNT_QTY`, **kg**.
- 매출: 정의서의 `ALL_INCM_AMT`, **원**. 비용을 뺀 순이익이 아니다.
- 입력: 품목, 지역, 단동/연동, 온실 규모 설명, 면적(㎡), 계획 시작 연도·월.
- 비교: 품목 중앙값, 면적당 품목 중앙값, CatBoost, XGBoost.
- 같은 시설은 학습·검증에 겹치지 않는다. 후보 선택에 사용한 교차검증 점수이므로 독립적인 최종 검증이나 미래연도 정확도를 뜻하지 않는다.

환경·생육·기상·특보·태풍 파일은 동봉한 명세로 컬럼·타입·키를 검사할 수 있다. 재배 후에 생기는 값은 도입 전 예측 입력으로 넣지 않는다. 종묘 주문·축산물·사진을 시설ID로 억지로 연결하지 않는다.

## 1. 예제로 먼저 실행

오프라인 ZIP은 **Windows x64 / Python 3.12**용 wheel 패키지를 포함한다. Python 설치 프로그램 자체와 GPU 가중치는 포함하지 않는다. 센터의 실제 운영체제·버전·반입 및 실행 허용 여부는 별도 확인 대상이다.

ZIP은 `C:\dsz`처럼 **짧고 쓰기 가능한 경로**에 풀고, `run_dsz.ps1`이 있는 폴더에서 PowerShell로 실행한다. 여러 프로젝트·압축해제 폴더 안에 깊게 넣으면 Windows 경로 길이 제한으로 scikit-learn 설치가 실패할 수 있다. 이 경우 시스템 보안 설정을 변경하지 말고 짧은 위치에 다시 풀거나 기존 설치 환경을 지정한다.

```powershell
.\run_dsz.ps1 -Demo
```

동봉 wheel만 사용해 `.venv-dsz`를 만들고, `runs\날짜_시각\` 아래 전처리·모델·예측 결과를 만든다. 이 과정에는 API 키나 인터넷 연결이 필요 없다. 예제는 **40개의 가상 시설 × 2작기, 5품목**이다. 결과의 `data_kind=synthetic_schema_fixture`는 반드시 유지한다. 수치가 좋아도 공모전의 실제 모델 정확도로 인용하지 않는다.

센터에 이미 호환 패키지가 설치돼 있으면 해당 Python을 지정할 수 있다.

```powershell
.\run_dsz.ps1 -Demo -Python 'C:\approved-python\python.exe' -UseExistingEnvironment
```

센터 정책상 스크립트 실행 방식이 정해져 있으면 아래 개별 Python 명령을 사용한다. 보안 설정을 변경할 필요는 없다.

## 2. 실제 파일로 실행

센터가 허용한 작업 폴더에 실제 데이터를 둔다. CSV는 헤더 포함 UTF-8을 기본으로 읽고 CP949는 명시적으로 선택한다. XLSX도 지원한다. 다른 원자료를 덮어쓰거나 예제 폴더에 섞지 않는다.

필수 파일은 `DZ_002.csv`와 `DZ_004.csv`이다. 각각 원본 표 이름 `M_DZ_SFARMFACILITY`, `M_DZ_SFARMMANAGEMENT`를 파일명으로 사용할 수도 있다. XLSX 규칙 등 상세 계약은 `dsz_schema_contract.md`를 따른다.

| 구분 | 연결에 필요한 필드 | 주요 입력·정답 |
|---|---|---|
| 시설 DZ_002 | `FRMTM_SNO`, `FCLT_ID`, `FRMTM_BGNG_YMD`, `FRMTM_END_YMD` | `ITEM_NM`, `AREA_NM`, `SACT_INTLCK_SPR_NM`, `HTHS_SCL_CN`, `HTHS_SFC` |
| 경영 DZ_004 | `EXMN_SNO`, `FCLT_ID`, `EXMN_YMD` | `ALL_SHPMNT_KGUNT_QTY`, `ALL_INCM_AMT` |

시설ID가 같고 조사일이 작기 시작·종료일 사이에 포함되는 **정확히 한 작기**만 연결한다. 기간이 겹치거나 어느 작기에도 연결되지 않는 행은 제외 사유를 남긴다. 적재일시는 조사일 대신 사용하지 않는다. 숫자형 식별자도 문자열로 보존한다.

### 경영조사 집계 방식은 실제 자료 의미에 맞춰 선택

정의서는 kg·원 단위는 명시하지만 각 조사행이 누계인지 증분인지는 명시하지 않는다. 다음 옵션은 코드가 확인한 사실이 아니라 **실행자가 선택해 기록하는 해석**이다.

| `-ManagementPolicy` | 사용할 상황 | 처리 |
|---|---|---|
| `single_record_per_cycle` (기본) | 작기마다 한 건의 총량 기록으로 해석할 때 | 조사행이 정확히 한 개인 작기만 사용 |
| `incremental_sum` | 각 조사행이 중복되지 않는 기간의 증분일 때 | 작기 내 합계. 결측이 섞인 타깃은 부분합으로 대체하지 않음 |
| `latest_cumulative` | 각 조사행이 해당 시점까지의 누계일 때 | 마지막 조사일의 고유한 기록 사용. 최종일 중복은 제외 |

마지막 누계도 작기 전체가 완결되었다는 보장은 없다. 실행한 해석과 제외 내역을 보고서에 함께 사용한다. 값 0은 관측값으로 남기고 결측을 0으로 채우지 않으며, 출하량·매출 적격 여부는 따로 판단한다.

새 농가 계획은 동봉 `data\examples\dsz\example_plans.csv`의 헤더를 복사해 실제 계획값으로 작성한다. 품목·지역·시설 표기는 실제 학습 데이터 표기와 맞춘다. 학습에 전혀 없던 품목은 예측하지 않는다.

```powershell
.\run_dsz.ps1 -InputDir 'D:\approved_work\farm_data' `
  -Plans 'D:\approved_work\plans.csv' `
  -ManagementPolicy single_record_per_cycle

# CP949 CSV이면 -Encoding cp949 추가
```

명령별 실행 또는 Windows 이외 환경의 설치된 Python 사용:

```text
python scripts/prepare_dsz.py --input-dir /approved/farm_data --output-dir runs/onsite/prepared --management-policy single_record_per_cycle
python scripts/train_dsz.py --data-dir runs/onsite/prepared --output-dir runs/onsite/models
python scripts/predict_dsz.py --artifact-dir runs/onsite/models --plans /approved/plans.csv --output runs/onsite/predictions.csv
```

## 3. 결과에서 먼저 볼 것

1. `prepared/dsz_validation.csv`: 컬럼·타입·키 검사.
2. `prepared/dsz_exclusions.csv`: 연결 실패·중복·결측 등에 따른 제외 사유.
3. `prepared/dsz_manifest.json`: 원본 해시, 사용된 집계 가정, 적격 행 수, 데이터 구분.
4. `models/dsz_model_metrics.json`: 타깃별 MAE/RMSE, 시설별 분할, 선택한 모델.
5. `models/`의 OOF CSV: 학습에서 빠진 시설의 실제값·예측값. kg와 원을 섞어 비교하지 않는다.
6. `predictions.csv`: 새 계획의 예측량·매출과 데이터 출처 구분. 단위가 작기 기준인지 확인하고 연간 손익 계산에 바로 대입하지 않는다.

관측행이 부족하면 임의 가짜행을 추가하지 않는다. 어떤 타깃이 학습 불가한지 출력과 제외표를 확인한다. 시설별 최소 2개 독립 그룹이 필요하며 더 많은 시설과 별도의 미래 기간 검증이 바람직하다. 저장 모델은 본인이 생성한 실행 산출물만 사용한다.

## LimiX-2와 기존 공개자료 실험

기존 프로젝트에서는 공개 원자료로 LimiX-2 400M을 실제 비교했다. DSZ 학습 CLI의 `--include-limix`는 승인된 GPU 환경·검토된 코드·기존 가중치를 준비한 전체 프로젝트에서 추가 비교할 때 사용한다. 이 CPU 반입 묶음은 네 가지 CPU 방법을 독립적으로 실행하며 LimiX 가중치를 다운로드하지 않는다.

반입·결과 반출은 센터의 절차를 따른다. 이 패키지의 예제 실행 완료가 실제 미개방 데이터 활용 실적이나 센터 실행 승인을 뜻하지 않는다. 실제 결과는 현장에서 원자료로 실행한 뒤 허용된 범위의 산출물로 정리한다.
