# 공개 웹 계산기

[Vercel 웹사이트](https://smartfarm-adoption.vercel.app)

별도 서버·데이터베이스·로그인 없이 브라우저에서 계산하는 Vercel 정적 사이트입니다. 입력값을 서버에 저장하지 않습니다. 기존 Python 연구 앱은 `app.py`에 유지됩니다.

공개 웹에는 딸기 전국 집계 기준의 계획 계산, 설비 구성, 세 가지 손익·현금흐름 시나리오, 입력 가정에 대한 민감도, 보관 가격·생육 실험 요약과 PPT 다운로드를 제공합니다. 미개방 원자료를 새로 학습하거나 개별 농가를 실시간 예측하는 서비스는 아닙니다.

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

`scripts/build_web.mjs`는 명시된 공개 파일만 `dist/`에 복사합니다. API 키·실제 농가별 기록·모델 가중치·학습용 산출물은 포함하지 않습니다.

- `reports/planning_demo_summary.json`: 공개 조사 기준과 시연 가정
- `data/processed/equipment_catalog.json`: 공개 장비 등록 가격
- `reports/planning_reference_scenarios.json`: 보관 가격·기후 기준의 시나리오
- `reports/price_forecast_metrics_summary.json`: 가격 실험 집계
- `reports/inseason_metrics_summary.json`: 생육 실험 집계

경제성 산식은 `src/economics.py`를 브라우저용 `economics.mjs`로 옮겼습니다. 민감도는 독립 삼각분포라는 동일한 가정을 사용하지만 JavaScript 난수 생성기는 NumPy와 달라 표본·백분위 수치가 정확히 같지는 않습니다. 민감도 범위는 가정의 결과이며 신뢰구간이나 성공 확률이 아닙니다.

글꼴은 원본 전체 글리프를 WOFF2로 변환한 주아체와 고운돋움체이며, `fonts/`에 각각의 OFL 라이선스가 있습니다. 입력·결과는 새로고침 시 초기화되고, 계산 결과는 사용자가 JSON 파일로 내려받을 수 있습니다.
