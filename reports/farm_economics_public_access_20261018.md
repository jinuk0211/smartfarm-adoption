# 동일 농가 경제성 원자료: 추가 공개 경로 확인

확인일: 2026-10-18. 기존 수집 내역과 공개 페이지·파일을 점검했습니다. 메일·문의·자료 신청·계정 생성은 진행하지 않았습니다. 새로 확보한 **딸기 동일 농가의 생산·판매·전체 비용·실제 투자액 결합 원자료는 0행**입니다. 공개 자료 전체에 그런 자료가 없다는 결론은 아닙니다.

## 기존 API와 신규 공개 파일

로컬 수집 내역과 수집기상 2026-10-09 목록의 238시설·651작기에 대해 출하·비용을 각각 651회 조회했습니다. 출하 2,823행·비용 99행이며 실패·생략·부분기간 요청 기록은 0회입니다. 요청 기간은 각 작기 시작일부터 종료일까지입니다.

[작기별 API](https://www.smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030105)와 [품목별 API](https://www.smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030104) 설명에서 목록 밖의 미수집 작기를 확인하지 못했습니다. [실시간 API](https://www.smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030101)의 환경·생육 확대를 비용 확보로 세지 않았습니다. 이번에 인증이 필요한 신규 조회는 하지 않았으며, 서버의 과거 행 수정이나 작기 밖 등록 비용의 존재는 확인하지 못했습니다.

[지역별 딸기 ICT생육 융복합 정보](https://data.mafra.go.kr/opendata/data/indexOpenDataDetail.do?data_id=20210928000000001573)의 경상북도 ZIP은 3개 CSV·11,373행·3시설·83컬럼입니다. 시설·품종·면적·재배형태·환경·제어·생육 정보가 있으나 **출하 kg·판매액·비목별 비용 컬럼은 없습니다.** 다른 지역 ZIP도 같다고 단정하지 않습니다. 확인 파일은 학습·경제성 자료에 합치거나 이 저장소에 재배포하지 않았습니다.

## 다른 경로의 확인 수준

| 경로 | 확인한 범위와 판단 |
|---|---|
| KADX 공개 검색 | 딸기·경영·소득·비용·스마트팜 검색 범위에서 요구한 결합 원자료 미확인 |
| [농산물소득조사 댓글게시판](https://www.data.go.kr/data/15123928/fileData.do) | 게시물·댓글·등록일 스키마이며 농가 소득 원자료가 아님 |
| [ADP 스마트팜 현장 농가 데이터](https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE) | 확보 자료에 비목별 비용·실제 설비 투자액 없음 |
| [MDIS 이용 안내](https://mdis.mods.go.kr/usr/joinBranch.do?curMenuNo=UI_POR_P9050) | 이용 절차 확인만 수행. 가입·신청·결합 원파일 확보 없음 |
| [농진청 경영개선 처방전 보도자료](https://m.korea.kr/briefing/pressReleaseView.do?newsId=156746737&pWise=mSub&pWiseSub=C3) | 참여 농가 대상 결과 제공 안내이며 전체 원자료 공개 다운로드가 아님 |

경제성 실증에는 동일 조사단위의 기간·면적·출하량·판매액·비용 범위와 실제 투자·교체비 근거가 더 필요합니다. 외부 평균·시범사업 지원액·시설 신조가격으로 대신하지 않습니다. 원자료 식별자·연락처·문의 초안·로컬 파일 링크는 공개하지 않습니다. [현재 연결 감사](farm_economics_evidence.md)
