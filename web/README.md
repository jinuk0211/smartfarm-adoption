# 공개 웹 계산기

[Vercel 웹사이트](https://smartfarm-adoption.vercel.app)

별도 서버·데이터베이스·로그인 없이 브라우저에서 계산하는 Vercel 정적 사이트입니다. 입력값을 서버에 저장하지 않습니다. 기존 Python 연구 앱은 `app.py`에 유지됩니다.

2026-10-18 로컬 보완은 `facility-plan.html`의 시설별 계획입니다. 메인 버튼이 이 페이지로 연결되며, 판매단가·비용·투자비는 공란에서 시작합니다. 시설·면적·재배조건·작기·연간 기간에 입력 근거를 묶고 변경 시 재확인합니다. 신규와 기존 시설 개량을 구분하고, 항목별 고정/출하량 비례 비용·교체 지출을 반영합니다. `facility-economics.mjs`의 결과는 Python `src/farm_economics.py`와 교차 검사합니다. 이 로컬 보완을 위 운영 주소에 배포한 상태는 아닙니다.

공개 웹에는 학습한 딸기 출하량·5품목 총매출 모델, 품목별 전국 조사 비용, 설비 구성, 손익·현금흐름·회수기간과 2,000회 가정 민감도를 제공합니다. 모델 모드를 선택하면 `prediction.mjs`가 수치 트리/중앙값 식을 실제 실행합니다. 사용자는 기록 작기를 연 1작기로 계산한다는 가정을 확인해야 합니다. [데이터·성능·연결 근거](../reports/planning_connection_validation.md)

기존 `index.html#planner` 계산기는 외부 평균 참고 예시입니다. 이것을 대상 시설의 실제 장부·전체 투자비를 확보한 경로로 표시하지 않습니다.

## 실행

Node.js 24를 사용합니다. 웹용 외부 JavaScript 패키지는 없습니다.

```powershell
npm run test:web
npm run build
python -m http.server 8513 --bind 127.0.0.1 --directory dist
```

`http://127.0.0.1:8513/`에서 확인합니다. 배포 설정은 루트의 `vercel.json`입니다.

Vercel 프로젝트는 `jinuk0211s-projects/smartfarm-adoption`입니다. 현재 배포는 CLI로 진행했으며 GitHub 자동 배포 연결은 되어 있지 않습니다. Git에 푸시하는 것만으로 웹사이트가 갱신되지는 않습니다. 미리보기는 `vercel deploy --target preview`, 위 공개 주소를 갱신하는 배포는 `vercel deploy --prod --scope jinuk0211s-projects`를 사용합니다.

## 데이터 범위

`scripts/build_web.mjs`는 명시된 공개 파일만 `dist/`에 복사합니다. 수치 모델 식과 집계 검증·공개 비용 참고를 포함하며 API 키·실제 농가별 행/시설ID·pickle/GPU 가중치·개별 OOF는 포함하지 않습니다. 모델 파일의 SHA256이 검증 보고서와 다르면 로딩을 중단합니다.

- `reports/planning_demo_summary.json`: 공개 조사 기준과 시연 가정
- `data/processed/equipment_catalog.json`: 공개 장비 등록 가격
- `reports/planning_reference_scenarios.json`: 보관 가격·기후 기준의 시나리오
- `reports/price_forecast_metrics_summary.json`: 가격 실험 집계
- `reports/inseason_metrics_summary.json`: 생육 실험 집계

경제성 산식은 `src/economics.py`를 브라우저용 `economics.mjs`로 옮겼습니다. 민감도는 독립 삼각분포라는 동일한 가정을 사용하지만 JavaScript 난수 생성기는 NumPy와 달라 표본·백분위 수치가 정확히 같지는 않습니다. 민감도 범위는 가정의 결과이며 신뢰구간이나 성공 확률이 아닙니다.

글꼴은 원본 전체 글리프를 WOFF2로 변환한 주아체와 고운돋움체이며, `fonts/`에 각각의 OFL 라이선스가 있습니다. 입력·결과는 새로고침 시 초기화되고, 계산 결과는 사용자가 JSON 파일로 내려받을 수 있습니다.
