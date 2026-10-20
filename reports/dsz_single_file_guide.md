# GitHub에서 받아 단일 Python 파일로 실행

지원·검증 환경은 **Python 3.12 / CPU**입니다. 고정 패키지 XGBoost 3.4.1은 Python 3.12 이상을 요구합니다.
GitHub와 패키지 저장소에 접속할 수 있고 패키지 설치가 가능한 센터 환경에서 사용합니다.

## 복사할 실행 명령

일반 터미널에서 실행합니다. 이 파일이 포함된 브랜치를 명시합니다.

```bash
git clone --depth 1 --branch codex/dsz-inseason-shipment https://github.com/jinuk0211/smartfarm-adoption.git
cd smartfarm-adoption
python -m pip install -r requirements-dsz-cpu.txt
python smartfarm_shipment.py
```

이미 받은 저장소라면 해당 폴더에서 로컬 변경을 보존한 상태로 이 브랜치의 최신 코드를 받습니다.
기존 노트북 커널과 별도 Python에 패키지를 나누어 설치하지 않도록 같은 Python을 사용하세요.

처음 실행은 **합성 데이터 데모**입니다. 딸기 16작기·8시설의 학습·검증과 새 가상 시설 예측이 실행됩니다.
실제 원자료나 검증된 실제 농가 정확도가 아닙니다. GPU·API 키·LimiX 가중치가 필요하지 않습니다.

## 실제 원자료 설정

[smartfarm_shipment.py](../smartfarm_shipment.py) 맨 위의 설정만 바꿉니다.
```python
MODE = "real"
REAL_HISTORY_DIR = r"D:\approved_data\history"
REAL_PERIOD_CONFIRMATION = r"D:\approved_data\period_confirmation.json"
REAL_CURRENT_DIR = r"D:\approved_data\current"
TARGET_FACILITY_ID = "실제 FCLT_ID"
TARGET_CYCLE_ID = "실제 FRMTM_SNO"
CUTOFF_DAYS = 30
```

Linux에서는 해당 환경의 절대 경로를 사용합니다. 원자료 파일명은 [명세서의 전체 이름](dsz_csv_format.md)을 유지하세요.
코드는 CSV·단일 시트 XLSX를 읽고 같은 시설·작기의 예측 시점 이전 관측을 연결합니다.
예측 대상 표가 과거 자료 폴더에 함께 있으면 REAL_CURRENT_DIR은 None으로 두어도 됩니다.
두 TARGET ID가 비어 있으면 검사·학습까지만 수행합니다. ID를 넣으면 요청 CSV는 자동으로 생성합니다.
학습에 사용한 시설의 재예측을 새로운 시설에 대한 검증 정확도로 해석하지 않습니다.

총출하량과 총수입이 실제 어느 기간의 기록인지 근거가 없다면 REAL_PERIOD_CONFIRMATION은 None으로 두고 검사부터 합니다.
조사일을 보고 작기 전체 합계라고 임의로 정하지 않습니다. 원자료·근거 문서·행·기간을 확인한 JSON 작성 방법은
[명세 계약](dsz_schema_contract.md)에 있습니다. 합성 예제의 기간 선언을 실제 데이터에 재사용하지 않습니다.
기간 근거가 없거나 일치하지 않으면 학습·예측으로 진행하지 않습니다.

## 처리와 결과

1. 명세서 파일명·영문 컬럼·타입·구분자 검사.
2. 시설·작기 연결과 출하량 집계기간 검사.
3. 예측일까지의 환경·생육·기상 요약.
4. 기본 7개 입력과 관측을 추가한 입력을 같은 시설 분할에서 비교.
5. 중앙값 기준선·CatBoost·XGBoost 비교 후 요청 시설의 **작기 전체 예상 출하량 kg** 출력.

30일·60일 모델은 CUTOFF_DAYS를 바꾸어 각각 학습합니다. 태풍은 현재 입력에서 제외합니다.
출하량만으로 소득·투자 회수·설비 설치의 인과효과를 확정하지 않습니다.

실행한 위치에 새 dsz_jupyter_날짜_고유번호 폴더가 생깁니다. 내부 보조 파일은 단일 실행 파일에서 자동 준비합니다.
결과는 그 안의 runs/ 폴더에 저장되며 화면에 정확한 경로가 나옵니다.
- predictions.csv: 요청 시설의 예상 작기 총출하량.
- models/dsz_inseason_metrics.json: 비교·검증 결과와 입력 출처.
- models/observation_audit.json: 관측 연결 검사.
- prepared/: 명세·연결·기간 검사 결과.

생성 작업 폴더는 .gitignore로 제외합니다. 센터 원자료와 파생 결과는 센터 내부에 두고 승인된 반출 절차를 따릅니다.
