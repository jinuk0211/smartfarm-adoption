# 대회 미개방 데이터: 명세서 기반 현장 실행 계약

사용자가 대구 안심구역 방문을 완료했으며 실제 데이터는 현장 안에서만 볼 수 있다고 설명했다. 이에 실제 파일이 들어올 경로와 전처리·모델 입력을 명세서대로 구현한다. 이 문서와 예제는 미개방 원자료를 외부에서 확보했거나 실제 데이터의 정확도를 검증했다는 증거가 아니다.

## 입력과 형식

원문은 `data/raw/dsz/epis_columns_user_supplied.txt`이며 `config/dsz_schema.json`에 DZ_001~007의 영문 컬럼명, Oracle 타입·길이, 키, 단위를 그대로 옮겼다. 경영 총출하량은 `NUMBER(20)` kg, 총수입은 `NUMBER(17,2)` 원, 시설면적은 `NUMBER(17,3)` ㎡다. 타입을 보고 표본 수·결측률·실제 품목 분포를 추정하지 않는다.

| 자료 | 입력 여부 | 이번 서비스 사용 |
|---|---|---|
| DZ_002 시설 | 필수 | 작기·시설 식별, 사전 계획 특성 |
| DZ_004 경영조사 | 필수 | 조사 기록의 출하량·매출 후보 목표값 |
| DZ_001 환경 / DZ_003 생육 | 선택 | 컬럼·타입·기본키 검증, 행 수 기록 |
| DZ_005 기상 / DZ_006 특보 / DZ_007 태풍 | 선택 | 컬럼·타입·기본키 검증, 행 수 기록 |
| DZ_008 이미지 / DZ_009 종묘 / DZ_010·011 축산 | 이 서비스의 입력에서 제외 | 앞의 두 자료에는 시설ID 연결 키가 없고 축산은 작물 도입 분석과 별도 거래 자료 |

각 파일은 `DZ_002.csv` 또는 원문 이름 `M_DZ_SFARMFACILITY.csv`처럼 제공한다. `.xlsx`도 허용하며 데이터셋당 한 시트다. 확장자·파일명 대소문자는 구분하지 않고 컬럼명은 정확히 일치해야 한다. 같은 데이터셋 파일을 두 개 주면 임의로 고르지 않고 오류를 낸다. UTF-8 BOM CSV가 기본이며 CP949는 `--encoding cp949`로 명시한다.

읽을 때 모든 원문 값을 문자열로 유지해 `00017` 같은 ID와 `NA` 같은 텍스트를 보존한다. XLSX에서 ID 자체가 텍스트로 저장되어야 선행 0을 보존할 수 있다. Excel 숫자 저장 단계에서 이미 유실된 0이나 정밀도를 복원하지 않는다. 원문의 VARCHAR2(8) 날짜는 YYYYMMDD를 요구하며 Oracle DATE는 YYYYMMDD, YYYY-MM-DD, 초 단위 ISO 시각 등 구현에 명시된 형식을 검증한다. 필수 파일의 모든 정의 컬럼은 있어야 하며 비키 값은 공란을 허용하되 모델에 필요한 값은 별도로 판정한다.

## 결합과 목표값

확인 근거가 없으면 시설ID가 같고 조사일이 작기 시작일~종료일 안에 들어오는 시설 작기를 찾아 감사 후보만 만든다. 이때 여러 작기에 매칭되거나 경계일이 겹치는 조사행은 제외한다. 확인 근거가 있으면 문서에 기반한 **원본 조사행→시설·작기 매핑**으로 연결하므로 작기 종료 뒤 조사한 정산을 다음 작기로 잘못 붙이지 않는다. 원본 시설ID·작기ID·기간·행번호를 대조하고 동일 원행의 중복 매핑을 허용하지 않는다. 유효한 작기에는 양의 면적, 품목·시설ID, 작기 시작연도 일치가 필요하다. 작기ID 기본키 중복·충돌은 허용하지 않는다.

`--management-policy`만으로는 학습 적격이 되지 않는다. 기본은 `target_period_confirmed=false`와 두 학습 적격 플래그 false이며 수치 유효성은 별도로 남긴다. `--period-confirmation`에 실제 정의 근거와 조사행별 집계기간을 연결하고 원본 해시·정책·시설/작기·기간 구조가 일치해야 확인된 후보로 취급한다. 확인 수준은 **문서에 근거한 검토자의 확인 기록**이며, 코드가 기관 확인이나 실제 수치의 정확성을 독립 검증했다는 뜻이 아니다.

| 모드 | 동작 | 기록되는 가정 |
|---|---|---|
| `single_record_per_cycle` (기본) | 유일한 조사행의 값 | 집계 시작·끝이 작기 전체와 같다는 근거 필요 |
| `incremental_sum` | 고유 조사키의 비음수 값을 합산. 한 목표라도 구성 값 하나가 결측·무효이면 그 목표 합계는 결측 | 행별 기간이 겹침·공백 없이 작기 전체를 덮는 증분이라는 근거 필요 |
| `latest_cumulative` | 가장 늦은 조사일의 유일한 행 사용. 최신 날짜가 중복이면 제외 | 각 행이 작기 시작부터 누계이고 최신 조사행이 작기말 최종 누계라는 근거 필요 |

확인 JSON의 필드는 다음과 같다. 경로가 상대경로이면 확인 JSON의 폴더를 기준으로 해석한다. 원본 CSV/Excel 행 번호는 헤더 다음인 2부터 시작한다. 자료에 없는 기간을 추정해 기입하지 않는다.

| 필드 | 내용 |
|---|---|
| `schema_version` | `1` |
| `policy`, `data_kind` | 실행 정책과 입력의 실제/합성 구분에 정확히 일치 |
| `target_columns` | `ALL_SHPMNT_KGUNT_QTY`, `ALL_INCM_AMT` 두 컬럼 |
| `source_files` | DZ_002와 DZ_004 각각의 `dataset`, `file`, `sha256` |
| `definition` | `path`, `sha256`, `locator`, `reviewed_by`, `reviewed_at`(YYYY-MM-DD), `aggregation_definition` |
| `cycles` | 각 `facility_id`, `cycle_id`, `start`, `end`, `records` |
| `cycles[].records` | 각 원본 조사행의 `source_row`, 집계 `start`, `end`(YYYY-MM-DD) |

두 목표의 집계기간이 다르면 이 공통 확인 구조로 통과시키지 않는다. 원자료 정의를 재확인해야 한다. 제공 명세서 자체에는 해당 집계기간 정의가 없으므로, 명세서 파일의 해시만 넣어 확인 완료라고 선언할 수 없다.

중복 조사키는 정확 중복이어도 자동 제거·합산하지 않고 관련 작기 후보를 제외한다. 해당 시설의 날짜가 해석되지 않는 조사 행은 어느 작기에 속할지 몰라 시설의 작기 후보를 제외하며 사유를 남긴다. 음수·잘못된 타입·결측 목표는 적격하지 않다. 0은 실제 기록값으로 보존하고 학습 대상이 될 수 있다. 출하량이 결측이어도 매출 목표가 적격하면 매출 학습에 사용 가능하며 그 반대도 가능하다. 총수입은 순이익으로 해석하지 않는다.

## 고정된 모델 입력

입력은 `crop`, `region`, `greenhouse_type`, `greenhouse_size`, `area_m2`, `planned_start_year`, `planned_start_month`의 7개다. 작기 시작 연월은 예측 시 사용자가 계획하는 시작 연월과 대응한다. 종료일·조사일·수입·출하량·생육·환경·사후 관측 기상·품질검사 결과·시설ID·작기ID는 예측 특성이 아니다. 시설ID는 교차검증 그룹으로만 사용한다. 과거 시설의 사전 상태라는 데이터 수집 의미까지 명세서로 입증된 것은 아니므로 실제 현장에서 점검해야 한다.

출력 `dsz_model_candidates.csv`에는 두 목표 `reported_shipment_kg`, `reported_revenue_krw`, 각 목표의 수치 유효성과 `shipment_eligible`, `revenue_eligible`, 기간 확인 여부·근거 JSON·해시, 시설·작기·원본 파일·행 번호와 원문 JSON이 함께 저장된다. 증분 합산의 원문 JSON에는 모든 구성 행이 남는다. 이 CSV 전체를 모델에 넣지 않고 고정 7개 열만 선택해야 한다. 학습·예측·기존 경제성 연결 CLI에서도 확인 근거를 검사하므로 오래된 미확정 산출물이나 boolean만 바꾼 후보는 사용할 수 없다.

기간이 확인된 후보와 미확정 후보가 섞여 있으면 원본 감사 CSV는 보존하고 확인된 적격 행만 모델에 전달한다. `training_cohort`에는 원본 후보 수, 사용 행, 미확정 제외 수, 확인됐지만 수치 등이 부적격인 제외 수, 사용 시설·작기·행과 해시가 남는다. 원본 전체의 `target_period_confirmed=false`를 지우거나 모델이 사용한 부분의 확인 상태와 혼동하지 않는다. 미확정 행을 적격이라고 표시한 변조는 거부한다.

실제 정의 근거 파일과 원본 파일의 해시는 **준비 단계**에서 대조한다. 이후 학습·예측은 신뢰하는 로컬 준비 산출물의 해시와 근거·선택 내역을 검사한다. 원본 파일을 매번 다시 읽는 기관 감사나 문서 의미의 자동 검증은 아니며, 임의로 작성한 선언 전체를 진실로 인증하는 기능도 아니다.

`dsz_validation.csv`는 타입·키 위반, `dsz_exclusions.csv`는 결합·적격성 제외 사유다. `dsz_manifest.json`은 원본 파일 해시, 명세서 해시, 출력 해시, 집계 가정, 단위, 인벤토리와 적격 행 수를 기록한다. 전처리를 시작할 때 패키지에 포함된 원문 명세서 파일의 실제 SHA256을 설정값과 대조하며 파일이 없거나 해시가 다르면 중단한다. 원본·정규화·예측 결과 파일은 현장 규정에 맞춰 보관하며 반출은 별도 절차를 따른다.

## 재현용 합성 데이터

`data/examples/dsz/input`의 40시설×2작기=80행은 난수 시드 142의 공개된 생성기로 만든 합성 데이터다. 모든 시설ID가 `SYN_FARM_`으로 시작하고 `fixture_manifest.json`에도 `data_kind=synthetic_schema_fixture`를 기록한다. 5품목은 파이프라인 분기 시연용으로 의도적으로 넣었다. 선택 자료는 각 1행이다. 원자료 분포나 실제 농가 반응을 재현한 것이 아니므로 여기서 계산한 성능을 실제 정확도로 보고할 수 없다.

예제 표식은 파일과 ID 두 경로로 감지하고 결과에 전파한다. 합성 ID와 실제처럼 보이는 ID를 섞으면 오류를 낸다. 표시가 없는 현장 입력은 `onsite_private_unverified`로 남겨 코드 실행 자체가 출처 검증이라는 인상을 주지 않는다.

```powershell
.venv\Scripts\python.exe data/examples/dsz/generate_fixture.py
.venv\Scripts\python.exe scripts/prepare_dsz.py --input-dir data/examples/dsz/input --output-dir data/examples/dsz/processed --period-confirmation data/examples/dsz/input/period_confirmation.json
.venv\Scripts\python.exe scripts/prepare_dsz.py --input-dir D:\approved_input --output-dir D:\local_results\prepared --encoding cp949 --management-policy single_record_per_cycle --period-confirmation D:\approved_input\period_confirmation.json
```

모델 코드에서 사용하는 파일 계약은 위 출력 CSV와 매니페스트다. CSV를 바꾼 뒤 기존 해시만 재사용하지 말고 전처리를 다시 실행해야 한다.
