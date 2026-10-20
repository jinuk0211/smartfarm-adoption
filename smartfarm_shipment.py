# ruff: noqa: E402
# 상단 사용자 설정과 단계별 실행 순서를 유지하기 위해 import 위치만 예외로 둡니다.
# 딸기 스마트팜 출하량 예측 — 단일 실행 파일
# Python: 이 파일을 실행합니다. 주피터: 같은 내용의 TXT 전체를 코드 셀 하나에 붙여 실행합니다.
# 아래 설정만 바꾸세요. 나머지에는 분석 코드·명세서·합성 예제가 모두 들어 있습니다.
# 내부 모듈을 새 작업 폴더에 자동 저장하므로, 별도 소스 파일을 준비할 필요가 없습니다.
# 네트워크 다운로드/패키지 자동 설치/실제 원자료 수정은 하지 않습니다.
# 분석: 표 읽기 → 시설·작기·기간 검사 → 같은 시설이 겹치지 않는 검증 → 작기 총출하량 kg 예측
# 실측 정답 기간이 확인되지 않으면 검사만 하며, 합성 점수는 실제 예측 성능이 아닙니다.
# Python 3.12 이상(검증: 3.12), numpy/pandas/scikit-learn/joblib/catboost/xgboost 필요.
# XLSX 입력에는 openpyxl도 필요합니다. CPU 경로이며 LimiX-2는 포함하지 않습니다.
#
# 명세서 ZIP 첫 시트에는 '스마트팜 우수농가 정보(환경)(M_DZ_SFARMENVIRONMENT).csv'처럼
# 전체 CSV 파일명이 나옵니다. 한글 전체 이름, 아래 영문명, DZ_00N 별칭을 지원합니다.
# 정식 CSV는 UTF-8·인용부호 없음, 구분자 | (기상특보만 쉼표)입니다.
# 기존 DZ_00N 쉼표 합성 예제도 지원합니다. 실제 필수 열이 맞는지 검사합니다.
# DZ_001 환경       M_DZ_SFARMENVIRONMENT
# DZ_002 시설       M_DZ_SFARMFACILITY
# DZ_003 생육       M_DZ_SFARMGROWTH
# DZ_004 경영조사   M_DZ_SFARMMANAGEINQUIRY (정의 시트의 M_DZ_SFARMMANAGEMENT도 지원)
# DZ_005 기상       M_DZ_WEATHER
# DZ_006 기상특보   M_DZ_WEATHERNEWSBREAK
# DZ_007 태풍       M_DZ_TYPHOON (검사만, 현재 모델 입력 제외)
# 한 폴더 바로 아래에 표별 한 파일이어야 합니다. 분할 CSV 자동 병합은 지원하지 않습니다.
# 컬럼은 명세서 영문명 전체를 유지합니다. CSV 인코딩 UTF-8 또는 CP949, XLSX 한 시트.
#
# 사용 순서:
# 1) 기본 demo로 합성 자료 실행 확인.
# 2) 실제 자료: MODE="real", REAL_HISTORY_DIR에 과거 자료 폴더 지정.
# 3) REAL_PERIOD_CONFIRMATION=None이면 명세·연결 검사만 합니다.
#    실제 총출하량/총수입 집계기간 근거 JSON을 지정해야 학습합니다.
#    합성 period_confirmation.json을 실제 데이터 근거로 재사용하면 안 됩니다.
# 4) TARGET_FACILITY_ID와 TARGET_CYCLE_ID를 실제 값으로 입력하면 예측까지 합니다.
#    예측 대상 표가 별도 폴더라면 REAL_CURRENT_DIR도 지정합니다.
#    TARGET 두 값을 비워 두면 검사/학습까지만 합니다.
#    학습에 포함된 시설의 재예측은 새로운 시설에 대한 정확도 검증이 아닙니다.
# 5) 화면에 출력한 새 작업 폴더의 predictions.csv와 models/ 검사·비교 결과를 확인합니다.
#    출력 출하량은 '작기 전체' kg이며 오늘 이후 남은 양이나 설비 도입 효과가 아닙니다.
#
# 실제 설정 예시(이 예시값은 실제 시설값으로 바꾸어야 합니다):
# MODE = "real"
# REAL_HISTORY_DIR = r"D:\approved_data\history"
# REAL_PERIOD_CONFIRMATION = r"D:\approved_data\period_confirmation.json"
# REAL_CURRENT_DIR = r"D:\approved_data\current"
# TARGET_FACILITY_ID = "실제 FCLT_ID"
# TARGET_CYCLE_ID = "실제 FRMTM_SNO"
# Linux 경로도 문자열로 지정할 수 있습니다. 실제 센터 실행환경에서 합성 확인 필요.

MODE = "demo"
REAL_HISTORY_DIR = None
REAL_PERIOD_CONFIRMATION = None
REAL_CURRENT_DIR = None  # None이면 예측에도 과거 자료 폴더 사용
TARGET_FACILITY_ID = ""  # 따옴표를 유지하여 ID의 선행 0 보존
TARGET_CYCLE_ID = ""
CUTOFF_DAYS = 30
WINDOW_DAYS = 28
CROP = "딸기"
ENCODING = "utf-8-sig"  # 필요하면 "cp949"
MANAGEMENT_POLICY = "single_record_per_cycle"  # 실제 확인된 집계 방식과 일치해야 함

# ===== 여기 아래는 수정하지 않아도 됩니다 =====

# %% 1. 현재 주피터 커널의 패키지 확인
import sys
import importlib
import importlib.metadata
import json
import subprocess
from pathlib import Path
from datetime import datetime
from uuid import uuid4

if sys.version_info < (3, 12):
    raise RuntimeError("고정 패키지 XGBoost 3.4.1에는 Python 3.12 이상이 필요합니다. 검증 환경은 Python 3.12입니다.")

print("Python:", sys.version)
print("현재 주피터 커널:", sys.executable)
REFERENCE_VERSIONS = {
    "numpy": ("numpy", "2.3.5"),
    "pandas": ("pandas", "3.0.1"),
    "sklearn": ("scikit-learn", "1.9.1"),
    "joblib": ("joblib", "1.6.0"),
    "catboost": ("catboost", "1.2.10"),
    "xgboost": ("xgboost", "3.4.1"),
}
failed_packages = []
for module_name, (distribution, reference) in REFERENCE_VERSIONS.items():
    try:
        importlib.import_module(module_name)
        actual = importlib.metadata.version(distribution)
        print(distribution, actual, "(로컬 검증 버전:", reference + ")")
    except Exception as error:
        failed_packages.append(distribution)
        print(distribution, "불러오기 실패:", error)
try:
    import openpyxl
    print("openpyxl", openpyxl.__version__, "(XLSX 읽기에 필요 / 검증 버전: 3.1.5)")
except Exception as error:
    print("openpyxl 사용 불가: CSV는 가능, XLSX를 쓰면 설치 필요:", error)
if failed_packages:
    raise RuntimeError("필요한 패키지 확인/설치 요청: " + ", ".join(failed_packages))

# 설치되어 있어도 버전이 다르면 합성 예제로 호환성을 확인합니다.
# 이 코드는 pip 설치나 인터넷 다운로드를 자동 실행하지 않습니다.


# ===== 내장 소스·명세·합성 예제: 원문 보존 =====
import hashlib

DSZ_ROOT = (Path.cwd() / ("dsz_jupyter_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])).resolve()
DSZ_ROOT.mkdir(exist_ok=False)
_SAVED_SOURCE_FILES = []

def _save_source(relative_path, text, newline, bom, expected_sha256):
    # 명세서와 합성 예제의 원본 해시를 보존하기 위해 줄바꿈과 BOM도 원래대로 저장합니다.
    target = (DSZ_ROOT / relative_path).resolve()
    if not target.is_relative_to(DSZ_ROOT):
        raise ValueError("작업 폴더 밖 경로는 허용하지 않습니다.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    payload = text.replace("\n", newline).encode("utf-8")
    if bom:
        payload = b"\xef\xbb\xbf" + payload
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("복사 내용이 원본과 다릅니다. 파일 전체를 다시 복사하세요: " + relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    _SAVED_SOURCE_FILES.append(relative_path)

# ===== SOURCE FILE: config/dsz_schema.json =====
_save_source("config/dsz_schema.json", r'''
{
  "schema_version": 1,
  "dictionary_path": "data/raw/dsz/epis_columns_user_supplied.txt",
  "dictionary_sha256": "fcbf6d647b64686775e847d575ed4e8bc9bb3b79b958f54c95dfe7289e09faff",
  "target_assumption": "single_record_per_cycle",
  "target_period_confirmed": false,
  "tables": {
    "DZ_001": {
      "label": "스마트팜 우수농가 정보(환경)",
      "filename": "M_DZ_SFARMENVIRONMENT",
      "export_filename": "스마트팜 우수농가 정보(환경)(M_DZ_SFARMENVIRONMENT).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": false,
      "columns": [
        {
          "name": "FRMTM_YR",
          "label": "작기연도",
          "key": "PK1",
          "type": "VARCHAR2(4)",
          "unit": "년",
          "description": "작물의 작기시작일자의 연도",
          "note": "—"
        },
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "PK2",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "농가의 시설에 부여되는 아이디",
          "note": "—"
        },
        {
          "name": "MSRM_DT",
          "label": "측정일시",
          "key": "PK3",
          "type": "DATE",
          "unit": "일시",
          "description": "환경정보의 수집시 측정된 년월일시분초 개념의 일시",
          "note": "—"
        },
        {
          "name": "INR_CO2_QTY_MRCNT",
          "label": "내부CO2량측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "ppm",
          "description": "온실내부 이산화탄소 측정값",
          "note": "—"
        },
        {
          "name": "DWPNT_TMPRT_MRCNT",
          "label": "이슬점온도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "도",
          "description": "이슬 (결로)이 형성되는 온도",
          "note": "—"
        },
        {
          "name": "INR_HMDT_MRCNT",
          "label": "내부습도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "％",
          "description": "온실내부 공기 중에 포함된 수증기의 양 또는 비율",
          "note": "—"
        },
        {
          "name": "ERTH_HMDT_MRCNT",
          "label": "대지습도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "％",
          "description": "대지의 공기 중에 포함된 수증기의 양 또는 비율",
          "note": "—"
        },
        {
          "name": "RNFAL_MRCNT",
          "label": "강우량측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "mm",
          "description": "강우량 측정값",
          "note": "—"
        },
        {
          "name": "SLRDQTY_MRCNT",
          "label": "일사량측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "W/m-2·s",
          "description": "태양으로부터 오는 태양 복사 에너지(일사(日射))가 지표에 닿는 양",
          "note": "—"
        },
        {
          "name": "EXTRNL_TMPRT_MRCNT",
          "label": "외부온도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "도",
          "description": "온실외부 측정된 온도 값",
          "note": "—"
        },
        {
          "name": "INR_TMPRT_MRCNT",
          "label": "내부온도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "도",
          "description": "온실내부 측정된 온도 값",
          "note": "—"
        },
        {
          "name": "ERTH_TMPRT_MRCNT",
          "label": "대지온도측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "도",
          "description": "대지의 측정된 온도 값",
          "note": "—"
        },
        {
          "name": "EXTRNL_WNDDRT_MRCNT",
          "label": "외부풍향측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "도",
          "description": "온실외부의 풍향 측정 값",
          "note": "—"
        },
        {
          "name": "EXTRNL_WNDSPD_MRCNT",
          "label": "외부풍속측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "m/s",
          "description": "온실외부의 풍속 측정 값",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_002": {
      "label": "스마트팜 우수농가 정보(시설)",
      "filename": "M_DZ_SFARMFACILITY",
      "export_filename": "스마트팜 우수농가 정보(시설)(M_DZ_SFARMFACILITY).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": true,
      "columns": [
        {
          "name": "FRMTM_SNO",
          "label": "작기일련번호",
          "key": "PK1",
          "type": "NUMBER(13)",
          "unit": "N/A",
          "description": "작기정보 등록시 부여되는 고유일련번호",
          "note": "—"
        },
        {
          "name": "FRMTM_YR",
          "label": "작기연도",
          "key": "—",
          "type": "VARCHAR2(4)",
          "unit": "년",
          "description": "작물의 작기시작일자의 연도",
          "note": "—"
        },
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "—",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "농가의 시설에 부여되는 아이디",
          "note": "—"
        },
        {
          "name": "ITEM_NM",
          "label": "품목명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "재배하는 품목의 명칭",
          "note": "—"
        },
        {
          "name": "AREA_NM",
          "label": "지역명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "시설이 위치하고 있는 지역의 명칭",
          "note": "—"
        },
        {
          "name": "SACT_INTLCK_SPR_NM",
          "label": "단동연동구분명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "재배시설의 온실의 유형명",
          "note": "—"
        },
        {
          "name": "HTHS_SCL_CN",
          "label": "온실규모내용",
          "key": "—",
          "type": "VARCHAR2(4000)",
          "unit": "N/A",
          "description": "온실의 규모에 대한 상세내용",
          "note": "—"
        },
        {
          "name": "FRMTM_BGNG_YMD",
          "label": "작기시작일자",
          "key": "—",
          "type": "VARCHAR2(8)",
          "unit": "일",
          "description": "작물의 작기시작일자",
          "note": "—"
        },
        {
          "name": "FRMTM_END_YMD",
          "label": "작기종료일자",
          "key": "—",
          "type": "VARCHAR2(8)",
          "unit": "일",
          "description": "작물의 작기종료일자",
          "note": "—"
        },
        {
          "name": "HTHS_SFC",
          "label": "온실면적",
          "key": "—",
          "type": "NUMBER(17,3)",
          "unit": "㎡",
          "description": "작물을 재배하는 온실의 면적",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_003": {
      "label": "스마트팜 우수농가 정보(생육)",
      "filename": "M_DZ_SFARMGROWTH",
      "export_filename": "스마트팜 우수농가 정보(생육)(M_DZ_SFARMGROWTH).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": false,
      "columns": [
        {
          "name": "FRMTM_YR",
          "label": "작기연도",
          "key": "PK1",
          "type": "VARCHAR2(4)",
          "unit": "년",
          "description": "작물의 작기시작일자의 연도",
          "note": "—"
        },
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "PK2",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "농가의 시설에 부여되는 아이디",
          "note": "—"
        },
        {
          "name": "EXMN_YMD",
          "label": "조사일자",
          "key": "PK3",
          "type": "DATE(8)",
          "unit": "일",
          "description": "생육정보를 조사한 일자",
          "note": "—"
        },
        {
          "name": "SMPL_SNO",
          "label": "표본일련번호",
          "key": "PK4",
          "type": "NUMBER(13)",
          "unit": "N/A",
          "description": "표본에 대해 부여된 번호",
          "note": "—"
        },
        {
          "name": "GRDV_NOFWK",
          "label": "생육주수",
          "key": "PK5",
          "type": "NUMBER(10)",
          "unit": "주",
          "description": "작기일에 자동으로 계산되는 해당 생육주차",
          "note": "—"
        },
        {
          "name": "FLVS_MMUNT_MRCNT",
          "label": "초장밀리미터단위측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "mm",
          "description": "지표면에서 생장점까지 (곡선)길이",
          "note": "—"
        },
        {
          "name": "LFLN_CMUNT_MRCNT",
          "label": "엽장센티미터단위측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "cm",
          "description": "맨 위에 개화 화방에서 3번째 해당하는 잎 길이(착과된 바로 위의 엽)",
          "note": "—"
        },
        {
          "name": "LFWD_CMUNT_MRCNT",
          "label": "엽폭센티미터단위측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "cm",
          "description": "맨 위에 개화 화방에서 3번째 해당하는 잎의 너비",
          "note": "—"
        },
        {
          "name": "ILFLN_CMUNT_MRCNT",
          "label": "엽병장센티미터단위측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "cm",
          "description": "관부에서 초장을 측정하는 잎의 하단까지의 길이(초장-엽장)",
          "note": "—"
        },
        {
          "name": "LF_MRCNT",
          "label": "엽측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "개",
          "description": "한 개체의 잎의 수(완전히 전개된 잎만 측정)",
          "note": "—"
        },
        {
          "name": "DMTR_MMUNT_MRCNT",
          "label": "관부직경밀리미터단위측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "mm",
          "description": "원줄기 관부에서 가장 굵은 부분의 길이",
          "note": "—"
        },
        {
          "name": "SFLWR_MRCNT",
          "label": "소화측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "개",
          "description": "화방에 달린 꽃의 수",
          "note": "—"
        },
        {
          "name": "FSTNG_MRCNT",
          "label": "착과측정결과수",
          "key": "—",
          "type": "NUMBER(10,2)",
          "unit": "개",
          "description": "화방에 달린 열매의 수(꽃잎이 떨어진 개수)",
          "note": "—"
        },
        {
          "name": "LAST_FGRP_SNO",
          "label": "최종화방일련번호",
          "key": "—",
          "type": "NUMBER(13)",
          "unit": "번",
          "description": "현재 개화 되어 있는 화방의 차수 기입",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_004": {
      "label": "스마트팜 우수농가 정보(경영조사)",
      "filename": "M_DZ_SFARMMANAGEMENT",
      "export_filename": "스마트팜 우수농가 정보(경영조사)(M_DZ_SFARMMANAGEINQUIRY).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "filename_aliases": [
        "M_DZ_SFARMMANAGEINQUIRY"
      ],
      "required": true,
      "columns": [
        {
          "name": "EXMN_SNO",
          "label": "조사일련번호",
          "key": "PK1",
          "type": "NUMBER(13)",
          "unit": "N/A",
          "description": "경영정보 등록시 부여되는 고유일련번호",
          "note": "—"
        },
        {
          "name": "EXMN_YMD",
          "label": "조사일자",
          "key": "—",
          "type": "VARCHAR2(8)",
          "unit": "일",
          "description": "조사한 일자",
          "note": "—"
        },
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "—",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "농가의 시설에 부여되는 아이디",
          "note": "—"
        },
        {
          "name": "ALL_SHPMNT_KGUNT_QTY",
          "label": "총출하킬로그램단위량",
          "key": "—",
          "type": "NUMBER(20)",
          "unit": "kg",
          "description": "재배한 품목의 출하된 무게",
          "note": "—"
        },
        {
          "name": "ALL_INCM_AMT",
          "label": "총수입금액",
          "key": "—",
          "type": "NUMBER(17,2)",
          "unit": "원",
          "description": "출하량에 대한 수입금액",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_005": {
      "label": "스마트팜 우수농가 정보(기상)",
      "filename": "M_DZ_WEATHER",
      "export_filename": "스마트팜 우수농가 정보(기상)(M_DZ_WEATHER).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": false,
      "columns": [
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "PK1",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "시설 ID를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_CDCN",
          "label": "관측지점코드내용",
          "key": "PK2",
          "type": "VARCHAR2(100)",
          "unit": "N/A",
          "description": "관측지점 코드를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_YMD",
          "label": "관측일자",
          "key": "PK3",
          "type": "VARCHAR2(8)",
          "unit": "일",
          "description": "관측일자를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_NM",
          "label": "관측지점명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "명칭",
          "description": "관측지점 명칭을 구분하는 값",
          "note": "—"
        },
        {
          "name": "TOP_TMPRT_MSRVL",
          "label": "최고온도측정값",
          "key": "—",
          "type": "NUMBER(12)",
          "unit": "도",
          "description": "최고온도 측정 값",
          "note": "—"
        },
        {
          "name": "LOWST_TMPRT_MSRVL",
          "label": "최저온도측정값",
          "key": "—",
          "type": "NUMBER(12)",
          "unit": "도",
          "description": "최저온도 측정 값",
          "note": "—"
        },
        {
          "name": "MAX_WNDSPD_MSRVL",
          "label": "최대풍속측정값",
          "key": "—",
          "type": "NUMBER(12)",
          "unit": "m/s",
          "description": "최대풍속 측정 값",
          "note": "—"
        },
        {
          "name": "DD_AVG_DWPTMP_MSRVL",
          "label": "일평균이슬점온도측정값",
          "key": "—",
          "type": "NUMBER(12)",
          "unit": "도",
          "description": "일평균이슬점온도 측정 값",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_006": {
      "label": "스마트팜 우수농가 정보(기상특보)",
      "filename": "M_DZ_WEATHERNEWSBREAK",
      "export_filename": "스마트팜 우수농가 정보(기상특보)(M_DZ_WEATHERNEWSBREAK).csv",
      "export_delimiter": ",",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": false,
      "columns": [
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "PK1",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "시설 ID를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_CDCN",
          "label": "관측지점코드내용",
          "key": "PK2",
          "type": "VARCHAR2(100)",
          "unit": "N/A",
          "description": "관측지점 코드를 구분하는 값",
          "note": "—"
        },
        {
          "name": "PRSTN_DT",
          "label": "발표일시",
          "key": "PK3",
          "type": "DATE",
          "unit": "일시",
          "description": "발표일시를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_NM",
          "label": "관측지점명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "관측지점 명칭을 구분하는 값",
          "note": "—"
        },
        {
          "name": "PRSTN_CN",
          "label": "발표내용",
          "key": "—",
          "type": "VARCHAR2(4000)",
          "unit": "N/A",
          "description": "기상특보 발표내용",
          "note": "—"
        },
        {
          "name": "NOTE_CN",
          "label": "비고내용",
          "key": "—",
          "type": "VARCHAR2(4000)",
          "unit": "N/A",
          "description": "기상특보 비고내용",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    },
    "DZ_007": {
      "label": "스마트팜 우수농가 정보(태풍)",
      "filename": "M_DZ_TYPHOON",
      "export_filename": "스마트팜 우수농가 정보(태풍)(M_DZ_TYPHOON).csv",
      "export_delimiter": "|",
      "export_quoting": false,
      "export_encoding": "utf-8",
      "required": false,
      "columns": [
        {
          "name": "FCLT_ID",
          "label": "시설ID",
          "key": "PK1",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "시설 ID를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_CDCN",
          "label": "관측지점코드내용",
          "key": "PK2",
          "type": "VARCHAR2(100)",
          "unit": "N/A",
          "description": "관측지점 코드를 구분하는 값",
          "note": "—"
        },
        {
          "name": "TPHN_ENG_NM",
          "label": "태풍영문명",
          "key": "PK3",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "태풍 영문명을 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_DT",
          "label": "관측일시",
          "key": "PK4",
          "type": "DATE",
          "unit": "일",
          "description": "관측일시를 구분하는 값",
          "note": "—"
        },
        {
          "name": "OBSV_PNT_NM",
          "label": "관측지점명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "관측지점 명칭을 구분하는 값",
          "note": "—"
        },
        {
          "name": "TPHN_NM",
          "label": "태풍명",
          "key": "—",
          "type": "VARCHAR2(200)",
          "unit": "N/A",
          "description": "태풍 명칭을 구분하는 값",
          "note": "—"
        },
        {
          "name": "TPHN_EXPCT_CN",
          "label": "태풍예상내용",
          "key": "—",
          "type": "VARCHAR2(4000)",
          "unit": "N/A",
          "description": "태풍 예상내용을 나타내는 값",
          "note": "—"
        },
        {
          "name": "MAX_WNDSPD_MSRVL",
          "label": "최대풍속측정값",
          "key": "—",
          "type": "NUMBER(12)",
          "unit": "m/s",
          "description": "최대풍속 측정값",
          "note": "—"
        },
        {
          "name": "STR_DT",
          "label": "적재일시",
          "key": "—",
          "type": "DATE",
          "unit": "일시",
          "description": "데이터 적재일시",
          "note": "—"
        },
        {
          "name": "STR_USERID",
          "label": "적재사용자ID",
          "key": "—",
          "type": "VARCHAR2(20)",
          "unit": "N/A",
          "description": "데이터 적재사용자 ID",
          "note": "—"
        }
      ]
    }
  },
  "excluded_datasets": {
    "DZ_008": "No facility ID or observation date defined; no direct farm join.",
    "DZ_009": "No facility ID defined; nursery orders are separate.",
    "DZ_010": "Livestock auction transactions are outside the crop adoption service.",
    "DZ_011": "Livestock auction transactions are outside the crop adoption service."
  }
}

'''[1:-1], "\r\n", False, "3c9f0ab084fe28e792c672a4b952e3ad0b5583f9f355145bcc639c602e07a5df")

# ===== SOURCE FILE: data/examples/dsz/example_plans.csv =====
_save_source("data/examples/dsz/example_plans.csv", r'''
crop,region,greenhouse_type,greenhouse_size,area_m2,planned_start_year,planned_start_month
딸기,경상남도 진주시,연동,2개 동,1000,2023,2

'''[1:-1], "\r\n", True, "ea0858cf4937f85cf43dfa20ff61d0f58dc23421ec349d62ce49ec02e4080e5d")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_001.csv =====
_save_source("data/examples/dsz/input/DZ_001.csv", r'''
FRMTM_YR,FCLT_ID,MSRM_DT,INR_CO2_QTY_MRCNT,DWPNT_TMPRT_MRCNT,INR_HMDT_MRCNT,ERTH_HMDT_MRCNT,RNFAL_MRCNT,SLRDQTY_MRCNT,EXTRNL_TMPRT_MRCNT,INR_TMPRT_MRCNT,ERTH_TMPRT_MRCNT,EXTRNL_WNDDRT_MRCNT,EXTRNL_WNDSPD_MRCNT,STR_DT,STR_USERID
2021,SYN_FARM_000,2021-01-10 12:00:00,510.20,,,,,,,,,,,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "b069d1b53f22215ab43fb02c78d6bb2cb7621b185a1fc0663efa6ef143e7f06e")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_002.csv =====
_save_source("data/examples/dsz/input/DZ_002.csv", r'''
FRMTM_SNO,FRMTM_YR,FCLT_ID,ITEM_NM,AREA_NM,SACT_INTLCK_SPR_NM,HTHS_SCL_CN,FRMTM_BGNG_YMD,FRMTM_END_YMD,HTHS_SFC,STR_DT,STR_USERID
1,2021,SYN_FARM_000,딸기,경상남도 진주시,연동,1개 동,20210101,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
41,2022,SYN_FARM_000,딸기,경상남도 진주시,연동,1개 동,20220101,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
2,2021,SYN_FARM_001,오이,충청남도 논산시,단동,2개 동,20210201,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
42,2022,SYN_FARM_001,오이,충청남도 논산시,단동,2개 동,20220201,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
3,2021,SYN_FARM_002,토마토,전북특별자치도 김제시,연동,3개 동,20210301,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
43,2022,SYN_FARM_002,토마토,전북특별자치도 김제시,연동,3개 동,20220301,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
4,2021,SYN_FARM_003,방울토마토,경상북도 상주시,단동,1개 동,20210101,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
44,2022,SYN_FARM_003,방울토마토,경상북도 상주시,단동,1개 동,20220101,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
5,2021,SYN_FARM_004,파프리카,경상남도 진주시,연동,2개 동,20210201,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
45,2022,SYN_FARM_004,파프리카,경상남도 진주시,연동,2개 동,20220201,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
6,2021,SYN_FARM_005,딸기,충청남도 논산시,단동,3개 동,20210301,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
46,2022,SYN_FARM_005,딸기,충청남도 논산시,단동,3개 동,20220301,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
7,2021,SYN_FARM_006,오이,전북특별자치도 김제시,연동,1개 동,20210101,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
47,2022,SYN_FARM_006,오이,전북특별자치도 김제시,연동,1개 동,20220101,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
8,2021,SYN_FARM_007,토마토,경상북도 상주시,단동,2개 동,20210201,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
48,2022,SYN_FARM_007,토마토,경상북도 상주시,단동,2개 동,20220201,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
9,2021,SYN_FARM_008,방울토마토,경상남도 진주시,연동,3개 동,20210301,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
49,2022,SYN_FARM_008,방울토마토,경상남도 진주시,연동,3개 동,20220301,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
10,2021,SYN_FARM_009,파프리카,충청남도 논산시,단동,1개 동,20210101,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
50,2022,SYN_FARM_009,파프리카,충청남도 논산시,단동,1개 동,20220101,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
11,2021,SYN_FARM_010,딸기,전북특별자치도 김제시,연동,2개 동,20210201,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
51,2022,SYN_FARM_010,딸기,전북특별자치도 김제시,연동,2개 동,20220201,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
12,2021,SYN_FARM_011,오이,경상북도 상주시,단동,3개 동,20210301,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
52,2022,SYN_FARM_011,오이,경상북도 상주시,단동,3개 동,20220301,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
13,2021,SYN_FARM_012,토마토,경상남도 진주시,연동,1개 동,20210101,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
53,2022,SYN_FARM_012,토마토,경상남도 진주시,연동,1개 동,20220101,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
14,2021,SYN_FARM_013,방울토마토,충청남도 논산시,단동,2개 동,20210201,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
54,2022,SYN_FARM_013,방울토마토,충청남도 논산시,단동,2개 동,20220201,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
15,2021,SYN_FARM_014,파프리카,전북특별자치도 김제시,연동,3개 동,20210301,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
55,2022,SYN_FARM_014,파프리카,전북특별자치도 김제시,연동,3개 동,20220301,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
16,2021,SYN_FARM_015,딸기,경상북도 상주시,단동,1개 동,20210101,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
56,2022,SYN_FARM_015,딸기,경상북도 상주시,단동,1개 동,20220101,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
17,2021,SYN_FARM_016,오이,경상남도 진주시,연동,2개 동,20210201,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
57,2022,SYN_FARM_016,오이,경상남도 진주시,연동,2개 동,20220201,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
18,2021,SYN_FARM_017,토마토,충청남도 논산시,단동,3개 동,20210301,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
58,2022,SYN_FARM_017,토마토,충청남도 논산시,단동,3개 동,20220301,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
19,2021,SYN_FARM_018,방울토마토,전북특별자치도 김제시,연동,1개 동,20210101,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
59,2022,SYN_FARM_018,방울토마토,전북특별자치도 김제시,연동,1개 동,20220101,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
20,2021,SYN_FARM_019,파프리카,경상북도 상주시,단동,2개 동,20210201,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
60,2022,SYN_FARM_019,파프리카,경상북도 상주시,단동,2개 동,20220201,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
21,2021,SYN_FARM_020,딸기,경상남도 진주시,연동,3개 동,20210301,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
61,2022,SYN_FARM_020,딸기,경상남도 진주시,연동,3개 동,20220301,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
22,2021,SYN_FARM_021,오이,충청남도 논산시,단동,1개 동,20210101,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
62,2022,SYN_FARM_021,오이,충청남도 논산시,단동,1개 동,20220101,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
23,2021,SYN_FARM_022,토마토,전북특별자치도 김제시,연동,2개 동,20210201,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
63,2022,SYN_FARM_022,토마토,전북특별자치도 김제시,연동,2개 동,20220201,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
24,2021,SYN_FARM_023,방울토마토,경상북도 상주시,단동,3개 동,20210301,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
64,2022,SYN_FARM_023,방울토마토,경상북도 상주시,단동,3개 동,20220301,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
25,2021,SYN_FARM_024,파프리카,경상남도 진주시,연동,1개 동,20210101,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
65,2022,SYN_FARM_024,파프리카,경상남도 진주시,연동,1개 동,20220101,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
26,2021,SYN_FARM_025,딸기,충청남도 논산시,단동,2개 동,20210201,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
66,2022,SYN_FARM_025,딸기,충청남도 논산시,단동,2개 동,20220201,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
27,2021,SYN_FARM_026,오이,전북특별자치도 김제시,연동,3개 동,20210301,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
67,2022,SYN_FARM_026,오이,전북특별자치도 김제시,연동,3개 동,20220301,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
28,2021,SYN_FARM_027,토마토,경상북도 상주시,단동,1개 동,20210101,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
68,2022,SYN_FARM_027,토마토,경상북도 상주시,단동,1개 동,20220101,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
29,2021,SYN_FARM_028,방울토마토,경상남도 진주시,연동,2개 동,20210201,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
69,2022,SYN_FARM_028,방울토마토,경상남도 진주시,연동,2개 동,20220201,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
30,2021,SYN_FARM_029,파프리카,충청남도 논산시,단동,3개 동,20210301,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
70,2022,SYN_FARM_029,파프리카,충청남도 논산시,단동,3개 동,20220301,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
31,2021,SYN_FARM_030,딸기,전북특별자치도 김제시,연동,1개 동,20210101,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
71,2022,SYN_FARM_030,딸기,전북특별자치도 김제시,연동,1개 동,20220101,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
32,2021,SYN_FARM_031,오이,경상북도 상주시,단동,2개 동,20210201,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
72,2022,SYN_FARM_031,오이,경상북도 상주시,단동,2개 동,20220201,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
33,2021,SYN_FARM_032,토마토,경상남도 진주시,연동,3개 동,20210301,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
73,2022,SYN_FARM_032,토마토,경상남도 진주시,연동,3개 동,20220301,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
34,2021,SYN_FARM_033,방울토마토,충청남도 논산시,단동,1개 동,20210101,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
74,2022,SYN_FARM_033,방울토마토,충청남도 논산시,단동,1개 동,20220101,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
35,2021,SYN_FARM_034,파프리카,전북특별자치도 김제시,연동,2개 동,20210201,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
75,2022,SYN_FARM_034,파프리카,전북특별자치도 김제시,연동,2개 동,20220201,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
36,2021,SYN_FARM_035,딸기,경상북도 상주시,단동,3개 동,20210301,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
76,2022,SYN_FARM_035,딸기,경상북도 상주시,단동,3개 동,20220301,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
37,2021,SYN_FARM_036,오이,경상남도 진주시,연동,1개 동,20210101,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
77,2022,SYN_FARM_036,오이,경상남도 진주시,연동,1개 동,20220101,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
38,2021,SYN_FARM_037,토마토,충청남도 논산시,단동,2개 동,20210201,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
78,2022,SYN_FARM_037,토마토,충청남도 논산시,단동,2개 동,20220201,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
39,2021,SYN_FARM_038,방울토마토,전북특별자치도 김제시,연동,3개 동,20210301,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
79,2022,SYN_FARM_038,방울토마토,전북특별자치도 김제시,연동,3개 동,20220301,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
40,2021,SYN_FARM_039,파프리카,경상북도 상주시,단동,1개 동,20210101,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
80,2022,SYN_FARM_039,파프리카,경상북도 상주시,단동,1개 동,20220101,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "1f5c64bd48410869f324e3dd5d88cac8d93b3e4d0e4a54b6027ce3c4158b63e7")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_003.csv =====
_save_source("data/examples/dsz/input/DZ_003.csv", r'''
FRMTM_YR,FCLT_ID,EXMN_YMD,SMPL_SNO,GRDV_NOFWK,FLVS_MMUNT_MRCNT,LFLN_CMUNT_MRCNT,LFWD_CMUNT_MRCNT,ILFLN_CMUNT_MRCNT,LF_MRCNT,DMTR_MMUNT_MRCNT,SFLWR_MRCNT,FSTNG_MRCNT,LAST_FGRP_SNO,STR_DT,STR_USERID
2021,SYN_FARM_000,20210110,1,2,104.00,,,,,,,,,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "3ab26bf948f5140350c70255649b0d0305b6e3bb5062fdee446097edab4fbc3c")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_004.csv =====
_save_source("data/examples/dsz/input/DZ_004.csv", r'''
EXMN_SNO,EXMN_YMD,FCLT_ID,ALL_SHPMNT_KGUNT_QTY,ALL_INCM_AMT,STR_DT,STR_USERID
1,20210630,SYN_FARM_000,2041,10138942.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
41,20220630,SYN_FARM_000,1894,8737636.19,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
2,20210630,SYN_FARM_001,6533,9395480.28,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
42,20220630,SYN_FARM_001,6273,11616095.84,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
3,20210630,SYN_FARM_002,7824,13244709.18,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
43,20220630,SYN_FARM_002,6937,12205482.70,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
4,20210630,SYN_FARM_003,4414,21242079.09,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
44,20220630,SYN_FARM_003,4708,21832741.75,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
5,20210630,SYN_FARM_004,7246,19541774.80,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
45,20220630,SYN_FARM_004,10056,24967441.42,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
6,20210630,SYN_FARM_005,4422,19256856.08,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
46,20220630,SYN_FARM_005,4363,25992170.84,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
7,20210630,SYN_FARM_006,13306,21175317.00,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
47,20220630,SYN_FARM_006,13620,18764236.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
8,20210630,SYN_FARM_007,7569,14036339.82,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
48,20220630,SYN_FARM_007,9266,18702179.52,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
9,20210630,SYN_FARM_008,2078,6754030.43,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
49,20220630,SYN_FARM_008,1825,7665178.63,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
10,20210630,SYN_FARM_009,3510,9801414.72,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
50,20220630,SYN_FARM_009,4036,15264834.00,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
11,20210630,SYN_FARM_010,3988,17298547.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
51,20220630,SYN_FARM_010,3577,15971641.53,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
12,20210630,SYN_FARM_011,6638,14537753.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
52,20220630,SYN_FARM_011,6255,11317919.71,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
13,20210630,SYN_FARM_012,8158,13510821.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
53,20220630,SYN_FARM_012,11244,29403105.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
14,20210630,SYN_FARM_013,8198,39198938.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
54,20220630,SYN_FARM_013,7961,39221486.23,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
15,20210630,SYN_FARM_014,12889,49521036.75,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
55,20220630,SYN_FARM_014,8806,28634370.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
16,20210630,SYN_FARM_015,4120,15887630.95,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
56,20220630,SYN_FARM_015,4133,23431220.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
17,20210630,SYN_FARM_016,2969,5390362.39,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
57,20220630,SYN_FARM_016,4242,9457517.16,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
18,20210630,SYN_FARM_017,6870,13774769.91,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
58,20220630,SYN_FARM_017,6806,15467542.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
19,20210630,SYN_FARM_018,4727,14388210.27,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
59,20220630,SYN_FARM_018,4114,16282462.14,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
20,20210630,SYN_FARM_019,5724,23414657.16,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
60,20220630,SYN_FARM_019,4754,13920767.72,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
21,20210630,SYN_FARM_020,4152,19616942.99,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
61,20220630,SYN_FARM_020,3995,17832874.14,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
22,20210630,SYN_FARM_021,9910,20490189.62,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
62,20220630,SYN_FARM_021,10986,18936401.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
23,20210630,SYN_FARM_022,10565,21210167.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
63,20220630,SYN_FARM_022,8965,23565648.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
24,20210630,SYN_FARM_023,7126,25291323.95,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
64,20220630,SYN_FARM_023,5683,23459138.18,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
25,20210630,SYN_FARM_024,3526,10027206.34,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
65,20220630,SYN_FARM_024,3498,9994195.61,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
26,20210630,SYN_FARM_025,2262,9541926.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
66,20220630,SYN_FARM_025,2619,15787617.78,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
27,20210630,SYN_FARM_026,8711,13053367.21,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
67,20220630,SYN_FARM_026,6106,12510399.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
28,20210630,SYN_FARM_027,6693,12109343.30,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
68,20220630,SYN_FARM_027,7160,14920636.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
29,20210630,SYN_FARM_028,5968,29772504.47,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
69,20220630,SYN_FARM_028,7533,32980858.65,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
30,20210630,SYN_FARM_029,5755,19798189.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
70,20220630,SYN_FARM_029,5562,17744619.53,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
31,20210630,SYN_FARM_030,3985,18200610.85,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
71,20220630,SYN_FARM_030,4969,19249139.39,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
32,20210630,SYN_FARM_031,12021,26439137.48,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
72,20220630,SYN_FARM_031,12608,21779380.02,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
33,20210630,SYN_FARM_032,3977,10472988.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
73,20220630,SYN_FARM_032,4161,8061266.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
34,20210630,SYN_FARM_033,3180,15765152.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
74,20220630,SYN_FARM_033,3749,13223761.31,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
35,20210630,SYN_FARM_034,6653,25915244.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
75,20220630,SYN_FARM_034,7019,23642093.22,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
36,20210630,SYN_FARM_035,2791,16600886.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
76,20220630,SYN_FARM_035,3160,15090057.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
37,20210630,SYN_FARM_036,8011,11852107.78,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
77,20220630,SYN_FARM_036,8162,16737679.66,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
38,20210630,SYN_FARM_037,10503,22344118.04,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
78,20220630,SYN_FARM_037,10237,23485154.43,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
39,20210630,SYN_FARM_038,9816,44163466.03,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
79,20220630,SYN_FARM_038,9061,33841128.83,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
40,20210630,SYN_FARM_039,11830,36176793.98,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
80,20220630,SYN_FARM_039,9784,27208869.46,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "e33ae15d961d669830a048367a4581990eb6c415ce05874b8df711edad5cb8c1")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_005.csv =====
_save_source("data/examples/dsz/input/DZ_005.csv", r'''
FCLT_ID,OBSV_PNT_CDCN,OBSV_YMD,OBSV_PNT_NM,TOP_TMPRT_MSRVL,LOWST_TMPRT_MSRVL,MAX_WNDSPD_MSRVL,DD_AVG_DWPTMP_MSRVL,STR_DT,STR_USERID
SYN_FARM_000,001,20210110,합성지점,18,,,,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "f6798aeb35076a72e619b55f6f501af8f8a89be5bca799b05883a28e65b4b657")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_006.csv =====
_save_source("data/examples/dsz/input/DZ_006.csv", r'''
FCLT_ID,OBSV_PNT_CDCN,PRSTN_DT,OBSV_PNT_NM,PRSTN_CN,NOTE_CN,STR_DT,STR_USERID
SYN_FARM_000,001,2021-01-10 12:00:00,합성지점,합성 특보,,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "b401fffea4e09fe9023295fa7518a6eb9dbebf38d393696fcf382b6ea845ac06")

# ===== SOURCE FILE: data/examples/dsz/input/DZ_007.csv =====
_save_source("data/examples/dsz/input/DZ_007.csv", r'''
FCLT_ID,OBSV_PNT_CDCN,TPHN_ENG_NM,OBSV_DT,OBSV_PNT_NM,TPHN_NM,TPHN_EXPCT_CN,MAX_WNDSPD_MSRVL,STR_DT,STR_USERID
SYN_FARM_000,001,SYNTHETIC,2021-01-10 12:00:00,,합성태풍,,,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "21c0bcf49d996290dbde1bf5f6a2c78ada1298f208094492bfeb5753ee17ed0f")

# ===== SOURCE FILE: data/examples/dsz/input/fixture_manifest.json =====
_save_source("data/examples/dsz/input/fixture_manifest.json", r'''
{
  "data_kind": "synthetic_schema_fixture",
  "seed": 142,
  "facility_count": 40,
  "cycle_count": 80,
  "purpose": "Execution and schema-contract demonstration only. No real farm measurements or predictive accuracy.",
  "generator": "data/examples/dsz/generate_fixture.py"
}

'''[1:-1], "\r\n", False, "7c33ef6941b8ef3f77596839aa3a6cdc9fd742fd1fefcb5b97b1ca34cbb54dc3")

# ===== SOURCE FILE: data/examples/dsz/input/period_confirmation.json =====
_save_source("data/examples/dsz/input/period_confirmation.json", r'''
{
  "schema_version": 1,
  "policy": "single_record_per_cycle",
  "data_kind": "synthetic_schema_fixture",
  "target_columns": [
    "ALL_SHPMNT_KGUNT_QTY",
    "ALL_INCM_AMT"
  ],
  "source_files": [
    {
      "dataset": "DZ_002",
      "file": "DZ_002.csv",
      "sha256": "1f5c64bd48410869f324e3dd5d88cac8d93b3e4d0e4a54b6027ce3c4158b63e7"
    },
    {
      "dataset": "DZ_004",
      "file": "DZ_004.csv",
      "sha256": "e33ae15d961d669830a048367a4581990eb6c415ce05874b8df711edad5cb8c1"
    }
  ],
  "definition": {
    "path": "synthetic_period_definition.txt",
    "sha256": "8c8f2501472a512c08a84360c256a788116b23538275d2e458e0a743e937e380",
    "locator": "lines 1-4",
    "reviewed_by": "synthetic fixture generator",
    "reviewed_at": "2026-10-18",
    "aggregation_definition": "One fictional record is the complete cycle shipment and gross revenue total."
  },
  "cycles": [
    {
      "facility_id": "SYN_FARM_000",
      "cycle_id": "1",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 2,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_000",
      "cycle_id": "41",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 3,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_001",
      "cycle_id": "2",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 4,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_001",
      "cycle_id": "42",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 5,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_002",
      "cycle_id": "3",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 6,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_002",
      "cycle_id": "43",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 7,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_003",
      "cycle_id": "4",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 8,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_003",
      "cycle_id": "44",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 9,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_004",
      "cycle_id": "5",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 10,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_004",
      "cycle_id": "45",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 11,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_005",
      "cycle_id": "6",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 12,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_005",
      "cycle_id": "46",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 13,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_006",
      "cycle_id": "7",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 14,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_006",
      "cycle_id": "47",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 15,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_007",
      "cycle_id": "8",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 16,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_007",
      "cycle_id": "48",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 17,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_008",
      "cycle_id": "9",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 18,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_008",
      "cycle_id": "49",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 19,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_009",
      "cycle_id": "10",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 20,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_009",
      "cycle_id": "50",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 21,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_010",
      "cycle_id": "11",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 22,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_010",
      "cycle_id": "51",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 23,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_011",
      "cycle_id": "12",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 24,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_011",
      "cycle_id": "52",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 25,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_012",
      "cycle_id": "13",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 26,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_012",
      "cycle_id": "53",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 27,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_013",
      "cycle_id": "14",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 28,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_013",
      "cycle_id": "54",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 29,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_014",
      "cycle_id": "15",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 30,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_014",
      "cycle_id": "55",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 31,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_015",
      "cycle_id": "16",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 32,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_015",
      "cycle_id": "56",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 33,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_016",
      "cycle_id": "17",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 34,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_016",
      "cycle_id": "57",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 35,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_017",
      "cycle_id": "18",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 36,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_017",
      "cycle_id": "58",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 37,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_018",
      "cycle_id": "19",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 38,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_018",
      "cycle_id": "59",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 39,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_019",
      "cycle_id": "20",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 40,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_019",
      "cycle_id": "60",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 41,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_020",
      "cycle_id": "21",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 42,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_020",
      "cycle_id": "61",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 43,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_021",
      "cycle_id": "22",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 44,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_021",
      "cycle_id": "62",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 45,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_022",
      "cycle_id": "23",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 46,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_022",
      "cycle_id": "63",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 47,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_023",
      "cycle_id": "24",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 48,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_023",
      "cycle_id": "64",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 49,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_024",
      "cycle_id": "25",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 50,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_024",
      "cycle_id": "65",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 51,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_025",
      "cycle_id": "26",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 52,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_025",
      "cycle_id": "66",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 53,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_026",
      "cycle_id": "27",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 54,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_026",
      "cycle_id": "67",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 55,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_027",
      "cycle_id": "28",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 56,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_027",
      "cycle_id": "68",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 57,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_028",
      "cycle_id": "29",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 58,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_028",
      "cycle_id": "69",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 59,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_029",
      "cycle_id": "30",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 60,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_029",
      "cycle_id": "70",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 61,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_030",
      "cycle_id": "31",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 62,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_030",
      "cycle_id": "71",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 63,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_031",
      "cycle_id": "32",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 64,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_031",
      "cycle_id": "72",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 65,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_032",
      "cycle_id": "33",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 66,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_032",
      "cycle_id": "73",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 67,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_033",
      "cycle_id": "34",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 68,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_033",
      "cycle_id": "74",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 69,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_034",
      "cycle_id": "35",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 70,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_034",
      "cycle_id": "75",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 71,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_035",
      "cycle_id": "36",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 72,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_035",
      "cycle_id": "76",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 73,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_036",
      "cycle_id": "37",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 74,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_036",
      "cycle_id": "77",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 75,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_037",
      "cycle_id": "38",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 76,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_037",
      "cycle_id": "78",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 77,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_038",
      "cycle_id": "39",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 78,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_038",
      "cycle_id": "79",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 79,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_039",
      "cycle_id": "40",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 80,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_039",
      "cycle_id": "80",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 81,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    }
  ]
}

'''[1:-1], "\r\n", False, "17505eaac37c57bca1c40717fcca0ba2da64c6d567dcd4ec78e1ae52165ad987")

# ===== SOURCE FILE: data/examples/dsz/input/synthetic_period_definition.txt =====
_save_source("data/examples/dsz/input/synthetic_period_definition.txt", r'''
SYNTHETIC EXECUTION FIXTURE ONLY. No real farm evidence or provider confirmation.
The generator defines each DZ_004 record as the full shipment and gross revenue total
for the matching DZ_002 facility cycle, from FRMTM_BGNG_YMD through FRMTM_END_YMD.
There is exactly one management record per fictional facility cycle.

'''[1:-1], "\r\n", False, "8c8f2501472a512c08a84360c256a788116b23538275d2e458e0a743e937e380")

# ===== SOURCE FILE: data/examples/dsz_inseason/generate_fixture.py =====
_save_source("data/examples/dsz_inseason/generate_fixture.py", r'''
"""Create visibly synthetic observation and query files; never real farm evidence."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent


def write_table(directory, table_id, rows, schema):
    columns = [column["name"] for column in schema["tables"][table_id]["columns"]]
    with (directory / f"{table_id}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def observations(directory, facilities, schema):
    rows = {key: [] for key in ["DZ_001", "DZ_003", "DZ_005"]}
    for index, facility in enumerate(facilities):
        start = datetime.strptime(facility["FRMTM_BGNG_YMD"], "%Y%m%d")
        for day in [1, 7, 14, 21, 28, 35, 60]:
            when = start + timedelta(days=day)
            common = {"FCLT_ID": facility["FCLT_ID"], "STR_DT": "2026-10-18 00:00:00",
                      "STR_USERID": "SYNTHETIC_FIXTURE"}
            for hour in [8, 16]:
                rows["DZ_001"].append({**common, "FRMTM_YR": str(start.year),
                    "MSRM_DT": when.replace(hour=hour).isoformat(sep=" "),
                    "INR_TMPRT_MRCNT": f"{18 + index % 4 + hour / 10:.2f}",
                    "EXTRNL_TMPRT_MRCNT": str(8 + index % 6),
                    "INR_CO2_QTY_MRCNT": str(450 + index * 2 + day),
                    "INR_HMDT_MRCNT": str(60 + index % 12)})
            for sample in [1, 2]:
                rows["DZ_003"].append({**common, "FRMTM_YR": str(start.year),
                    "EXMN_YMD": when.strftime("%Y%m%d"), "SMPL_SNO": str(sample),
                    "GRDV_NOFWK": str(day // 7 + 1),
                    "FLVS_MMUNT_MRCNT": str(90 + day + index + sample),
                    "DMTR_MMUNT_MRCNT": f"{8 + day / 20 + sample / 10:.2f}",
                    "FSTNG_MRCNT": str(day // 14)})
            rows["DZ_005"].append({**common, "OBSV_PNT_CDCN": "SYN001",
                "OBSV_YMD": when.strftime("%Y%m%d"), "OBSV_PNT_NM": "합성관측소",
                "TOP_TMPRT_MSRVL": str(14 + index % 5), "LOWST_TMPRT_MSRVL": str(3 + index % 4),
                "MAX_WNDSPD_MSRVL": "3", "DD_AVG_DWPTMP_MSRVL": "2.00"})
    for key, records in rows.items():
        write_table(directory, key, records, schema)


def main():
    schema = json.loads((ROOT / "config/dsz_schema.json").read_text(encoding="utf-8"))
    source = ROOT / "data/examples/dsz/input"
    training, query = HERE / "input", HERE / "query"
    training.mkdir(parents=True, exist_ok=True)
    query.mkdir(parents=True, exist_ok=True)
    for name in ["DZ_002.csv", "DZ_004.csv", "period_confirmation.json", "synthetic_period_definition.txt"]:
        shutil.copyfile(source / name, training / name)
    with (source / "DZ_002.csv").open(encoding="utf-8-sig", newline="") as stream:
        strawberries = [row for row in csv.DictReader(stream) if row["ITEM_NM"] == "딸기"]
    observations(training, strawberries, schema)
    facility = {**strawberries[0], "FCLT_ID": "SYN_FARM_QUERY_001", "FRMTM_SNO": "9001",
                "FRMTM_YR": "2025", "FRMTM_BGNG_YMD": "20250101", "FRMTM_END_YMD": "",
                "STR_USERID": "SYNTHETIC_FIXTURE"}
    write_table(query, "DZ_002", [facility], schema)
    observations(query, [facility], schema)
    (HERE / "requests.csv").write_text(
        "plan_id,facility_id,cycle_id\nSYN_PLAN_001,SYN_FARM_QUERY_001,9001\n", encoding="utf-8-sig")
    marker = {"data_kind": "synthetic_schema_fixture", "purpose": "Execution only, not predictive evidence.",
              "generator": "data/examples/dsz_inseason/generate_fixture.py",
              "training_strawberry_cycles": len(strawberries), "query_is_unseen_synthetic_facility": True,
              "observations_are_not_fitted_to_shipment": True}
    for directory in [training, query]:
        (directory / "fixture_manifest.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

'''[1:-1], "\n", False, "40abb3b0a3a916611c75e3894039b95b2454e7c4abe66c4df8fb541f5c17b688")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/DZ_001.csv =====
_save_source("data/examples/dsz_inseason/input/DZ_001.csv", r'''
FRMTM_YR,FCLT_ID,MSRM_DT,INR_CO2_QTY_MRCNT,DWPNT_TMPRT_MRCNT,INR_HMDT_MRCNT,ERTH_HMDT_MRCNT,RNFAL_MRCNT,SLRDQTY_MRCNT,EXTRNL_TMPRT_MRCNT,INR_TMPRT_MRCNT,ERTH_TMPRT_MRCNT,EXTRNL_WNDDRT_MRCNT,EXTRNL_WNDSPD_MRCNT,STR_DT,STR_USERID
2021,SYN_FARM_000,2021-01-02 08:00:00,451,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-02 16:00:00,451,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-08 08:00:00,457,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-08 16:00:00,457,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-15 08:00:00,464,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-15 16:00:00,464,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-22 08:00:00,471,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-22 16:00:00,471,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-29 08:00:00,478,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-01-29 16:00:00,478,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-02-05 08:00:00,485,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-02-05 16:00:00,485,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-03-02 08:00:00,510,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,2021-03-02 16:00:00,510,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-02 08:00:00,453,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-02 16:00:00,453,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-08 08:00:00,459,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-08 16:00:00,459,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-15 08:00:00,466,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-15 16:00:00,466,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-22 08:00:00,473,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-22 16:00:00,473,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-29 08:00:00,480,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-01-29 16:00:00,480,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-02-05 08:00:00,487,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-02-05 16:00:00,487,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-03-02 08:00:00,512,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,2022-03-02 16:00:00,512,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-02 08:00:00,455,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-02 16:00:00,455,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-08 08:00:00,461,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-08 16:00:00,461,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-15 08:00:00,468,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-15 16:00:00,468,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-22 08:00:00,475,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-22 16:00:00,475,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-29 08:00:00,482,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-03-29 16:00:00,482,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-04-05 08:00:00,489,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-04-05 16:00:00,489,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-04-30 08:00:00,514,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,2021-04-30 16:00:00,514,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-02 08:00:00,457,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-02 16:00:00,457,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-08 08:00:00,463,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-08 16:00:00,463,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-15 08:00:00,470,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-15 16:00:00,470,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-22 08:00:00,477,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-22 16:00:00,477,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-29 08:00:00,484,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-03-29 16:00:00,484,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-04-05 08:00:00,491,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-04-05 16:00:00,491,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-04-30 08:00:00,516,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,2022-04-30 16:00:00,516,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-02 08:00:00,459,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-02 16:00:00,459,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-08 08:00:00,465,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-08 16:00:00,465,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-15 08:00:00,472,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-15 16:00:00,472,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-22 08:00:00,479,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-02-22 16:00:00,479,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-03-01 08:00:00,486,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-03-01 16:00:00,486,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-03-08 08:00:00,493,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-03-08 16:00:00,493,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-04-02 08:00:00,518,,64,,,,12,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,2021-04-02 16:00:00,518,,64,,,,12,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-02 08:00:00,461,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-02 16:00:00,461,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-08 08:00:00,467,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-08 16:00:00,467,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-15 08:00:00,474,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-15 16:00:00,474,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-22 08:00:00,481,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-02-22 16:00:00,481,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-03-01 08:00:00,488,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-03-01 16:00:00,488,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-03-08 08:00:00,495,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-03-08 16:00:00,495,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-04-02 08:00:00,520,,65,,,,13,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,2022-04-02 16:00:00,520,,65,,,,13,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-02 08:00:00,463,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-02 16:00:00,463,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-08 08:00:00,469,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-08 16:00:00,469,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-15 08:00:00,476,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-15 16:00:00,476,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-22 08:00:00,483,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-22 16:00:00,483,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-29 08:00:00,490,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-01-29 16:00:00,490,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-02-05 08:00:00,497,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-02-05 16:00:00,497,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-03-02 08:00:00,522,,66,,,,8,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,2021-03-02 16:00:00,522,,66,,,,8,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-02 08:00:00,465,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-02 16:00:00,465,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-08 08:00:00,471,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-08 16:00:00,471,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-15 08:00:00,478,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-15 16:00:00,478,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-22 08:00:00,485,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-22 16:00:00,485,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-29 08:00:00,492,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-01-29 16:00:00,492,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-02-05 08:00:00,499,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-02-05 16:00:00,499,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-03-02 08:00:00,524,,67,,,,9,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,2022-03-02 16:00:00,524,,67,,,,9,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-02 08:00:00,467,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-02 16:00:00,467,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-08 08:00:00,473,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-08 16:00:00,473,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-15 08:00:00,480,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-15 16:00:00,480,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-22 08:00:00,487,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-22 16:00:00,487,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-29 08:00:00,494,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-03-29 16:00:00,494,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-04-05 08:00:00,501,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-04-05 16:00:00,501,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-04-30 08:00:00,526,,68,,,,10,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,2021-04-30 16:00:00,526,,68,,,,10,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-02 08:00:00,469,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-02 16:00:00,469,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-08 08:00:00,475,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-08 16:00:00,475,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-15 08:00:00,482,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-15 16:00:00,482,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-22 08:00:00,489,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-22 16:00:00,489,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-29 08:00:00,496,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-03-29 16:00:00,496,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-04-05 08:00:00,503,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-04-05 16:00:00,503,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-04-30 08:00:00,528,,69,,,,11,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,2022-04-30 16:00:00,528,,69,,,,11,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-02 08:00:00,471,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-02 16:00:00,471,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-08 08:00:00,477,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-08 16:00:00,477,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-15 08:00:00,484,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-15 16:00:00,484,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-22 08:00:00,491,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-02-22 16:00:00,491,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-03-01 08:00:00,498,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-03-01 16:00:00,498,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-03-08 08:00:00,505,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-03-08 16:00:00,505,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-04-02 08:00:00,530,,70,,,,12,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,2021-04-02 16:00:00,530,,70,,,,12,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-02 08:00:00,473,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-02 16:00:00,473,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-08 08:00:00,479,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-08 16:00:00,479,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-15 08:00:00,486,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-15 16:00:00,486,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-22 08:00:00,493,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-02-22 16:00:00,493,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-03-01 08:00:00,500,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-03-01 16:00:00,500,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-03-08 08:00:00,507,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-03-08 16:00:00,507,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-04-02 08:00:00,532,,71,,,,13,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,2022-04-02 16:00:00,532,,71,,,,13,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-02 08:00:00,475,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-02 16:00:00,475,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-08 08:00:00,481,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-08 16:00:00,481,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-15 08:00:00,488,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-15 16:00:00,488,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-22 08:00:00,495,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-22 16:00:00,495,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-29 08:00:00,502,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-01-29 16:00:00,502,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-02-05 08:00:00,509,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-02-05 16:00:00,509,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-03-02 08:00:00,534,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,2021-03-02 16:00:00,534,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-02 08:00:00,477,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-02 16:00:00,477,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-08 08:00:00,483,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-08 16:00:00,483,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-15 08:00:00,490,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-15 16:00:00,490,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-22 08:00:00,497,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-22 16:00:00,497,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-29 08:00:00,504,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-01-29 16:00:00,504,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-02-05 08:00:00,511,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-02-05 16:00:00,511,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-03-02 08:00:00,536,,61,,,,9,19.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,2022-03-02 16:00:00,536,,61,,,,9,20.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-02 08:00:00,479,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-02 16:00:00,479,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-08 08:00:00,485,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-08 16:00:00,485,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-15 08:00:00,492,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-15 16:00:00,492,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-22 08:00:00,499,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-22 16:00:00,499,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-29 08:00:00,506,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-03-29 16:00:00,506,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-04-05 08:00:00,513,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-04-05 16:00:00,513,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-04-30 08:00:00,538,,62,,,,10,20.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,2021-04-30 16:00:00,538,,62,,,,10,21.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-02 08:00:00,481,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-02 16:00:00,481,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-08 08:00:00,487,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-08 16:00:00,487,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-15 08:00:00,494,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-15 16:00:00,494,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-22 08:00:00,501,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-22 16:00:00,501,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-29 08:00:00,508,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-03-29 16:00:00,508,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-04-05 08:00:00,515,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-04-05 16:00:00,515,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-04-30 08:00:00,540,,63,,,,11,21.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,2022-04-30 16:00:00,540,,63,,,,11,22.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "504ce22eea58fdaf4f051762717a6b0eedd8c1e8bc86e718c8c4592df037a896")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/DZ_002.csv =====
_save_source("data/examples/dsz_inseason/input/DZ_002.csv", r'''
FRMTM_SNO,FRMTM_YR,FCLT_ID,ITEM_NM,AREA_NM,SACT_INTLCK_SPR_NM,HTHS_SCL_CN,FRMTM_BGNG_YMD,FRMTM_END_YMD,HTHS_SFC,STR_DT,STR_USERID
1,2021,SYN_FARM_000,딸기,경상남도 진주시,연동,1개 동,20210101,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
41,2022,SYN_FARM_000,딸기,경상남도 진주시,연동,1개 동,20220101,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
2,2021,SYN_FARM_001,오이,충청남도 논산시,단동,2개 동,20210201,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
42,2022,SYN_FARM_001,오이,충청남도 논산시,단동,2개 동,20220201,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
3,2021,SYN_FARM_002,토마토,전북특별자치도 김제시,연동,3개 동,20210301,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
43,2022,SYN_FARM_002,토마토,전북특별자치도 김제시,연동,3개 동,20220301,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
4,2021,SYN_FARM_003,방울토마토,경상북도 상주시,단동,1개 동,20210101,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
44,2022,SYN_FARM_003,방울토마토,경상북도 상주시,단동,1개 동,20220101,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
5,2021,SYN_FARM_004,파프리카,경상남도 진주시,연동,2개 동,20210201,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
45,2022,SYN_FARM_004,파프리카,경상남도 진주시,연동,2개 동,20220201,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
6,2021,SYN_FARM_005,딸기,충청남도 논산시,단동,3개 동,20210301,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
46,2022,SYN_FARM_005,딸기,충청남도 논산시,단동,3개 동,20220301,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
7,2021,SYN_FARM_006,오이,전북특별자치도 김제시,연동,1개 동,20210101,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
47,2022,SYN_FARM_006,오이,전북특별자치도 김제시,연동,1개 동,20220101,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
8,2021,SYN_FARM_007,토마토,경상북도 상주시,단동,2개 동,20210201,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
48,2022,SYN_FARM_007,토마토,경상북도 상주시,단동,2개 동,20220201,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
9,2021,SYN_FARM_008,방울토마토,경상남도 진주시,연동,3개 동,20210301,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
49,2022,SYN_FARM_008,방울토마토,경상남도 진주시,연동,3개 동,20220301,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
10,2021,SYN_FARM_009,파프리카,충청남도 논산시,단동,1개 동,20210101,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
50,2022,SYN_FARM_009,파프리카,충청남도 논산시,단동,1개 동,20220101,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
11,2021,SYN_FARM_010,딸기,전북특별자치도 김제시,연동,2개 동,20210201,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
51,2022,SYN_FARM_010,딸기,전북특별자치도 김제시,연동,2개 동,20220201,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
12,2021,SYN_FARM_011,오이,경상북도 상주시,단동,3개 동,20210301,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
52,2022,SYN_FARM_011,오이,경상북도 상주시,단동,3개 동,20220301,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
13,2021,SYN_FARM_012,토마토,경상남도 진주시,연동,1개 동,20210101,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
53,2022,SYN_FARM_012,토마토,경상남도 진주시,연동,1개 동,20220101,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
14,2021,SYN_FARM_013,방울토마토,충청남도 논산시,단동,2개 동,20210201,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
54,2022,SYN_FARM_013,방울토마토,충청남도 논산시,단동,2개 동,20220201,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
15,2021,SYN_FARM_014,파프리카,전북특별자치도 김제시,연동,3개 동,20210301,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
55,2022,SYN_FARM_014,파프리카,전북특별자치도 김제시,연동,3개 동,20220301,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
16,2021,SYN_FARM_015,딸기,경상북도 상주시,단동,1개 동,20210101,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
56,2022,SYN_FARM_015,딸기,경상북도 상주시,단동,1개 동,20220101,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
17,2021,SYN_FARM_016,오이,경상남도 진주시,연동,2개 동,20210201,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
57,2022,SYN_FARM_016,오이,경상남도 진주시,연동,2개 동,20220201,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
18,2021,SYN_FARM_017,토마토,충청남도 논산시,단동,3개 동,20210301,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
58,2022,SYN_FARM_017,토마토,충청남도 논산시,단동,3개 동,20220301,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
19,2021,SYN_FARM_018,방울토마토,전북특별자치도 김제시,연동,1개 동,20210101,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
59,2022,SYN_FARM_018,방울토마토,전북특별자치도 김제시,연동,1개 동,20220101,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
20,2021,SYN_FARM_019,파프리카,경상북도 상주시,단동,2개 동,20210201,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
60,2022,SYN_FARM_019,파프리카,경상북도 상주시,단동,2개 동,20220201,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
21,2021,SYN_FARM_020,딸기,경상남도 진주시,연동,3개 동,20210301,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
61,2022,SYN_FARM_020,딸기,경상남도 진주시,연동,3개 동,20220301,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
22,2021,SYN_FARM_021,오이,충청남도 논산시,단동,1개 동,20210101,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
62,2022,SYN_FARM_021,오이,충청남도 논산시,단동,1개 동,20220101,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
23,2021,SYN_FARM_022,토마토,전북특별자치도 김제시,연동,2개 동,20210201,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
63,2022,SYN_FARM_022,토마토,전북특별자치도 김제시,연동,2개 동,20220201,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
24,2021,SYN_FARM_023,방울토마토,경상북도 상주시,단동,3개 동,20210301,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
64,2022,SYN_FARM_023,방울토마토,경상북도 상주시,단동,3개 동,20220301,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
25,2021,SYN_FARM_024,파프리카,경상남도 진주시,연동,1개 동,20210101,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
65,2022,SYN_FARM_024,파프리카,경상남도 진주시,연동,1개 동,20220101,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
26,2021,SYN_FARM_025,딸기,충청남도 논산시,단동,2개 동,20210201,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
66,2022,SYN_FARM_025,딸기,충청남도 논산시,단동,2개 동,20220201,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
27,2021,SYN_FARM_026,오이,전북특별자치도 김제시,연동,3개 동,20210301,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
67,2022,SYN_FARM_026,오이,전북특별자치도 김제시,연동,3개 동,20220301,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
28,2021,SYN_FARM_027,토마토,경상북도 상주시,단동,1개 동,20210101,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
68,2022,SYN_FARM_027,토마토,경상북도 상주시,단동,1개 동,20220101,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
29,2021,SYN_FARM_028,방울토마토,경상남도 진주시,연동,2개 동,20210201,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
69,2022,SYN_FARM_028,방울토마토,경상남도 진주시,연동,2개 동,20220201,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
30,2021,SYN_FARM_029,파프리카,충청남도 논산시,단동,3개 동,20210301,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
70,2022,SYN_FARM_029,파프리카,충청남도 논산시,단동,3개 동,20220301,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
31,2021,SYN_FARM_030,딸기,전북특별자치도 김제시,연동,1개 동,20210101,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
71,2022,SYN_FARM_030,딸기,전북특별자치도 김제시,연동,1개 동,20220101,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
32,2021,SYN_FARM_031,오이,경상북도 상주시,단동,2개 동,20210201,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
72,2022,SYN_FARM_031,오이,경상북도 상주시,단동,2개 동,20220201,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
33,2021,SYN_FARM_032,토마토,경상남도 진주시,연동,3개 동,20210301,20210630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
73,2022,SYN_FARM_032,토마토,경상남도 진주시,연동,3개 동,20220301,20220630,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
34,2021,SYN_FARM_033,방울토마토,충청남도 논산시,단동,1개 동,20210101,20210630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
74,2022,SYN_FARM_033,방울토마토,충청남도 논산시,단동,1개 동,20220101,20220630,750,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
35,2021,SYN_FARM_034,파프리카,전북특별자치도 김제시,연동,2개 동,20210201,20210630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
75,2022,SYN_FARM_034,파프리카,전북특별자치도 김제시,연동,2개 동,20220201,20220630,900,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
36,2021,SYN_FARM_035,딸기,경상북도 상주시,단동,3개 동,20210301,20210630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
76,2022,SYN_FARM_035,딸기,경상북도 상주시,단동,3개 동,20220301,20220630,1050,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
37,2021,SYN_FARM_036,오이,경상남도 진주시,연동,1개 동,20210101,20210630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
77,2022,SYN_FARM_036,오이,경상남도 진주시,연동,1개 동,20220101,20220630,1200,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
38,2021,SYN_FARM_037,토마토,충청남도 논산시,단동,2개 동,20210201,20210630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
78,2022,SYN_FARM_037,토마토,충청남도 논산시,단동,2개 동,20220201,20220630,1350,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
39,2021,SYN_FARM_038,방울토마토,전북특별자치도 김제시,연동,3개 동,20210301,20210630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
79,2022,SYN_FARM_038,방울토마토,전북특별자치도 김제시,연동,3개 동,20220301,20220630,1500,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
40,2021,SYN_FARM_039,파프리카,경상북도 상주시,단동,1개 동,20210101,20210630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
80,2022,SYN_FARM_039,파프리카,경상북도 상주시,단동,1개 동,20220101,20220630,1650,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "1f5c64bd48410869f324e3dd5d88cac8d93b3e4d0e4a54b6027ce3c4158b63e7")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/DZ_003.csv =====
_save_source("data/examples/dsz_inseason/input/DZ_003.csv", r'''
FRMTM_YR,FCLT_ID,EXMN_YMD,SMPL_SNO,GRDV_NOFWK,FLVS_MMUNT_MRCNT,LFLN_CMUNT_MRCNT,LFWD_CMUNT_MRCNT,ILFLN_CMUNT_MRCNT,LF_MRCNT,DMTR_MMUNT_MRCNT,SFLWR_MRCNT,FSTNG_MRCNT,LAST_FGRP_SNO,STR_DT,STR_USERID
2021,SYN_FARM_000,20210102,1,1,92,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210102,2,1,93,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210108,1,2,98,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210108,2,2,99,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210115,1,3,105,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210115,2,3,106,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210122,1,4,112,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210122,2,4,113,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210129,1,5,119,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210129,2,5,120,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210205,1,6,126,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210205,2,6,127,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210302,1,9,151,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_000,20210302,2,9,152,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220102,1,1,93,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220102,2,1,94,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220108,1,2,99,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220108,2,2,100,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220115,1,3,106,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220115,2,3,107,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220122,1,4,113,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220122,2,4,114,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220129,1,5,120,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220129,2,5,121,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220205,1,6,127,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220205,2,6,128,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220302,1,9,152,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_000,20220302,2,9,153,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210302,1,1,94,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210302,2,1,95,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210308,1,2,100,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210308,2,2,101,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210315,1,3,107,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210315,2,3,108,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210322,1,4,114,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210322,2,4,115,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210329,1,5,121,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210329,2,5,122,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210405,1,6,128,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210405,2,6,129,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210430,1,9,153,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_005,20210430,2,9,154,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220302,1,1,95,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220302,2,1,96,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220308,1,2,101,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220308,2,2,102,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220315,1,3,108,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220315,2,3,109,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220322,1,4,115,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220322,2,4,116,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220329,1,5,122,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220329,2,5,123,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220405,1,6,129,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220405,2,6,130,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220430,1,9,154,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_005,20220430,2,9,155,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210202,1,1,96,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210202,2,1,97,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210208,1,2,102,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210208,2,2,103,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210215,1,3,109,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210215,2,3,110,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210222,1,4,116,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210222,2,4,117,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210301,1,5,123,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210301,2,5,124,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210308,1,6,130,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210308,2,6,131,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210402,1,9,155,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_010,20210402,2,9,156,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220202,1,1,97,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220202,2,1,98,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220208,1,2,103,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220208,2,2,104,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220215,1,3,110,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220215,2,3,111,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220222,1,4,117,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220222,2,4,118,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220301,1,5,124,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220301,2,5,125,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220308,1,6,131,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220308,2,6,132,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220402,1,9,156,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_010,20220402,2,9,157,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210102,1,1,98,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210102,2,1,99,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210108,1,2,104,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210108,2,2,105,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210115,1,3,111,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210115,2,3,112,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210122,1,4,118,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210122,2,4,119,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210129,1,5,125,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210129,2,5,126,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210205,1,6,132,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210205,2,6,133,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210302,1,9,157,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_015,20210302,2,9,158,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220102,1,1,99,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220102,2,1,100,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220108,1,2,105,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220108,2,2,106,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220115,1,3,112,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220115,2,3,113,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220122,1,4,119,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220122,2,4,120,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220129,1,5,126,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220129,2,5,127,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220205,1,6,133,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220205,2,6,134,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220302,1,9,158,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_015,20220302,2,9,159,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210302,1,1,100,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210302,2,1,101,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210308,1,2,106,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210308,2,2,107,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210315,1,3,113,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210315,2,3,114,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210322,1,4,120,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210322,2,4,121,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210329,1,5,127,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210329,2,5,128,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210405,1,6,134,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210405,2,6,135,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210430,1,9,159,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_020,20210430,2,9,160,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220302,1,1,101,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220302,2,1,102,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220308,1,2,107,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220308,2,2,108,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220315,1,3,114,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220315,2,3,115,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220322,1,4,121,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220322,2,4,122,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220329,1,5,128,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220329,2,5,129,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220405,1,6,135,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220405,2,6,136,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220430,1,9,160,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_020,20220430,2,9,161,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210202,1,1,102,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210202,2,1,103,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210208,1,2,108,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210208,2,2,109,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210215,1,3,115,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210215,2,3,116,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210222,1,4,122,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210222,2,4,123,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210301,1,5,129,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210301,2,5,130,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210308,1,6,136,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210308,2,6,137,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210402,1,9,161,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_025,20210402,2,9,162,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220202,1,1,103,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220202,2,1,104,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220208,1,2,109,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220208,2,2,110,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220215,1,3,116,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220215,2,3,117,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220222,1,4,123,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220222,2,4,124,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220301,1,5,130,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220301,2,5,131,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220308,1,6,137,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220308,2,6,138,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220402,1,9,162,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_025,20220402,2,9,163,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210102,1,1,104,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210102,2,1,105,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210108,1,2,110,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210108,2,2,111,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210115,1,3,117,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210115,2,3,118,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210122,1,4,124,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210122,2,4,125,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210129,1,5,131,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210129,2,5,132,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210205,1,6,138,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210205,2,6,139,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210302,1,9,163,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_030,20210302,2,9,164,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220102,1,1,105,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220102,2,1,106,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220108,1,2,111,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220108,2,2,112,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220115,1,3,118,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220115,2,3,119,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220122,1,4,125,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220122,2,4,126,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220129,1,5,132,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220129,2,5,133,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220205,1,6,139,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220205,2,6,140,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220302,1,9,164,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_030,20220302,2,9,165,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210302,1,1,106,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210302,2,1,107,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210308,1,2,112,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210308,2,2,113,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210315,1,3,119,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210315,2,3,120,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210322,1,4,126,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210322,2,4,127,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210329,1,5,133,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210329,2,5,134,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210405,1,6,140,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210405,2,6,141,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210430,1,9,165,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2021,SYN_FARM_035,20210430,2,9,166,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220302,1,1,107,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220302,2,1,108,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220308,1,2,113,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220308,2,2,114,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220315,1,3,120,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220315,2,3,121,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220322,1,4,127,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220322,2,4,128,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220329,1,5,134,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220329,2,5,135,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220405,1,6,141,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220405,2,6,142,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220430,1,9,166,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2022,SYN_FARM_035,20220430,2,9,167,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "af8f30da161433376f3a020bb2716d1830ce52be7e63031cbdf3a71e072abe8e")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/DZ_004.csv =====
_save_source("data/examples/dsz_inseason/input/DZ_004.csv", r'''
EXMN_SNO,EXMN_YMD,FCLT_ID,ALL_SHPMNT_KGUNT_QTY,ALL_INCM_AMT,STR_DT,STR_USERID
1,20210630,SYN_FARM_000,2041,10138942.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
41,20220630,SYN_FARM_000,1894,8737636.19,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
2,20210630,SYN_FARM_001,6533,9395480.28,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
42,20220630,SYN_FARM_001,6273,11616095.84,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
3,20210630,SYN_FARM_002,7824,13244709.18,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
43,20220630,SYN_FARM_002,6937,12205482.70,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
4,20210630,SYN_FARM_003,4414,21242079.09,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
44,20220630,SYN_FARM_003,4708,21832741.75,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
5,20210630,SYN_FARM_004,7246,19541774.80,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
45,20220630,SYN_FARM_004,10056,24967441.42,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
6,20210630,SYN_FARM_005,4422,19256856.08,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
46,20220630,SYN_FARM_005,4363,25992170.84,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
7,20210630,SYN_FARM_006,13306,21175317.00,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
47,20220630,SYN_FARM_006,13620,18764236.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
8,20210630,SYN_FARM_007,7569,14036339.82,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
48,20220630,SYN_FARM_007,9266,18702179.52,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
9,20210630,SYN_FARM_008,2078,6754030.43,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
49,20220630,SYN_FARM_008,1825,7665178.63,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
10,20210630,SYN_FARM_009,3510,9801414.72,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
50,20220630,SYN_FARM_009,4036,15264834.00,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
11,20210630,SYN_FARM_010,3988,17298547.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
51,20220630,SYN_FARM_010,3577,15971641.53,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
12,20210630,SYN_FARM_011,6638,14537753.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
52,20220630,SYN_FARM_011,6255,11317919.71,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
13,20210630,SYN_FARM_012,8158,13510821.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
53,20220630,SYN_FARM_012,11244,29403105.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
14,20210630,SYN_FARM_013,8198,39198938.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
54,20220630,SYN_FARM_013,7961,39221486.23,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
15,20210630,SYN_FARM_014,12889,49521036.75,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
55,20220630,SYN_FARM_014,8806,28634370.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
16,20210630,SYN_FARM_015,4120,15887630.95,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
56,20220630,SYN_FARM_015,4133,23431220.90,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
17,20210630,SYN_FARM_016,2969,5390362.39,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
57,20220630,SYN_FARM_016,4242,9457517.16,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
18,20210630,SYN_FARM_017,6870,13774769.91,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
58,20220630,SYN_FARM_017,6806,15467542.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
19,20210630,SYN_FARM_018,4727,14388210.27,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
59,20220630,SYN_FARM_018,4114,16282462.14,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
20,20210630,SYN_FARM_019,5724,23414657.16,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
60,20220630,SYN_FARM_019,4754,13920767.72,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
21,20210630,SYN_FARM_020,4152,19616942.99,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
61,20220630,SYN_FARM_020,3995,17832874.14,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
22,20210630,SYN_FARM_021,9910,20490189.62,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
62,20220630,SYN_FARM_021,10986,18936401.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
23,20210630,SYN_FARM_022,10565,21210167.76,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
63,20220630,SYN_FARM_022,8965,23565648.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
24,20210630,SYN_FARM_023,7126,25291323.95,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
64,20220630,SYN_FARM_023,5683,23459138.18,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
25,20210630,SYN_FARM_024,3526,10027206.34,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
65,20220630,SYN_FARM_024,3498,9994195.61,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
26,20210630,SYN_FARM_025,2262,9541926.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
66,20220630,SYN_FARM_025,2619,15787617.78,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
27,20210630,SYN_FARM_026,8711,13053367.21,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
67,20220630,SYN_FARM_026,6106,12510399.01,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
28,20210630,SYN_FARM_027,6693,12109343.30,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
68,20220630,SYN_FARM_027,7160,14920636.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
29,20210630,SYN_FARM_028,5968,29772504.47,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
69,20220630,SYN_FARM_028,7533,32980858.65,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
30,20210630,SYN_FARM_029,5755,19798189.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
70,20220630,SYN_FARM_029,5562,17744619.53,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
31,20210630,SYN_FARM_030,3985,18200610.85,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
71,20220630,SYN_FARM_030,4969,19249139.39,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
32,20210630,SYN_FARM_031,12021,26439137.48,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
72,20220630,SYN_FARM_031,12608,21779380.02,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
33,20210630,SYN_FARM_032,3977,10472988.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
73,20220630,SYN_FARM_032,4161,8061266.60,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
34,20210630,SYN_FARM_033,3180,15765152.12,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
74,20220630,SYN_FARM_033,3749,13223761.31,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
35,20210630,SYN_FARM_034,6653,25915244.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
75,20220630,SYN_FARM_034,7019,23642093.22,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
36,20210630,SYN_FARM_035,2791,16600886.79,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
76,20220630,SYN_FARM_035,3160,15090057.37,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
37,20210630,SYN_FARM_036,8011,11852107.78,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
77,20220630,SYN_FARM_036,8162,16737679.66,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
38,20210630,SYN_FARM_037,10503,22344118.04,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
78,20220630,SYN_FARM_037,10237,23485154.43,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
39,20210630,SYN_FARM_038,9816,44163466.03,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
79,20220630,SYN_FARM_038,9061,33841128.83,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
40,20210630,SYN_FARM_039,11830,36176793.98,2022-08-01 10:00:00,SYNTHETIC_FIXTURE
80,20220630,SYN_FARM_039,9784,27208869.46,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "e33ae15d961d669830a048367a4581990eb6c415ce05874b8df711edad5cb8c1")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/DZ_005.csv =====
_save_source("data/examples/dsz_inseason/input/DZ_005.csv", r'''
FCLT_ID,OBSV_PNT_CDCN,OBSV_YMD,OBSV_PNT_NM,TOP_TMPRT_MSRVL,LOWST_TMPRT_MSRVL,MAX_WNDSPD_MSRVL,DD_AVG_DWPTMP_MSRVL,STR_DT,STR_USERID
SYN_FARM_000,SYN001,20210102,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210108,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210115,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210122,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210129,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210205,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20210302,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220102,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220108,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220115,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220122,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220129,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220205,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_000,SYN001,20220302,합성관측소,15,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210302,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210308,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210315,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210322,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210329,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210405,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20210430,합성관측소,16,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220302,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220308,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220315,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220322,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220329,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220405,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_005,SYN001,20220430,합성관측소,17,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210202,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210208,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210215,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210222,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210301,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210308,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20210402,합성관측소,18,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220202,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220208,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220215,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220222,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220301,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220308,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_010,SYN001,20220402,합성관측소,14,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210102,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210108,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210115,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210122,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210129,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210205,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20210302,합성관측소,15,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220102,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220108,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220115,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220122,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220129,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220205,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_015,SYN001,20220302,합성관측소,16,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210302,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210308,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210315,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210322,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210329,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210405,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20210430,합성관측소,17,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220302,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220308,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220315,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220322,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220329,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220405,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_020,SYN001,20220430,합성관측소,18,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210202,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210208,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210215,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210222,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210301,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210308,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20210402,합성관측소,14,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220202,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220208,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220215,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220222,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220301,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220308,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_025,SYN001,20220402,합성관측소,15,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210102,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210108,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210115,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210122,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210129,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210205,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20210302,합성관측소,16,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220102,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220108,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220115,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220122,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220129,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220205,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_030,SYN001,20220302,합성관측소,17,4,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210302,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210308,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210315,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210322,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210329,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210405,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20210430,합성관측소,18,5,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220302,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220308,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220315,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220322,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220329,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220405,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_035,SYN001,20220430,합성관측소,14,6,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "19e29afe2f67a1d8ff892e86b5838c2d9a2e5d6cb945bcafd2b3bbf71e3d98a2")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/fixture_manifest.json =====
_save_source("data/examples/dsz_inseason/input/fixture_manifest.json", r'''
{
  "data_kind": "synthetic_schema_fixture",
  "purpose": "Execution only, not predictive evidence.",
  "generator": "data/examples/dsz_inseason/generate_fixture.py",
  "training_strawberry_cycles": 16,
  "query_is_unseen_synthetic_facility": true,
  "observations_are_not_fitted_to_shipment": true
}

'''[1:-1], "\r\n", False, "72c0542733c0c9ea8d796e2974f1ba34e2916e10b4259ef23740254e6d143506")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/period_confirmation.json =====
_save_source("data/examples/dsz_inseason/input/period_confirmation.json", r'''
{
  "schema_version": 1,
  "policy": "single_record_per_cycle",
  "data_kind": "synthetic_schema_fixture",
  "target_columns": [
    "ALL_SHPMNT_KGUNT_QTY",
    "ALL_INCM_AMT"
  ],
  "source_files": [
    {
      "dataset": "DZ_002",
      "file": "DZ_002.csv",
      "sha256": "1f5c64bd48410869f324e3dd5d88cac8d93b3e4d0e4a54b6027ce3c4158b63e7"
    },
    {
      "dataset": "DZ_004",
      "file": "DZ_004.csv",
      "sha256": "e33ae15d961d669830a048367a4581990eb6c415ce05874b8df711edad5cb8c1"
    }
  ],
  "definition": {
    "path": "synthetic_period_definition.txt",
    "sha256": "8c8f2501472a512c08a84360c256a788116b23538275d2e458e0a743e937e380",
    "locator": "lines 1-4",
    "reviewed_by": "synthetic fixture generator",
    "reviewed_at": "2026-10-18",
    "aggregation_definition": "One fictional record is the complete cycle shipment and gross revenue total."
  },
  "cycles": [
    {
      "facility_id": "SYN_FARM_000",
      "cycle_id": "1",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 2,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_000",
      "cycle_id": "41",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 3,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_001",
      "cycle_id": "2",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 4,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_001",
      "cycle_id": "42",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 5,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_002",
      "cycle_id": "3",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 6,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_002",
      "cycle_id": "43",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 7,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_003",
      "cycle_id": "4",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 8,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_003",
      "cycle_id": "44",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 9,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_004",
      "cycle_id": "5",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 10,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_004",
      "cycle_id": "45",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 11,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_005",
      "cycle_id": "6",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 12,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_005",
      "cycle_id": "46",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 13,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_006",
      "cycle_id": "7",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 14,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_006",
      "cycle_id": "47",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 15,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_007",
      "cycle_id": "8",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 16,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_007",
      "cycle_id": "48",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 17,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_008",
      "cycle_id": "9",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 18,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_008",
      "cycle_id": "49",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 19,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_009",
      "cycle_id": "10",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 20,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_009",
      "cycle_id": "50",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 21,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_010",
      "cycle_id": "11",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 22,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_010",
      "cycle_id": "51",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 23,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_011",
      "cycle_id": "12",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 24,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_011",
      "cycle_id": "52",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 25,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_012",
      "cycle_id": "13",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 26,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_012",
      "cycle_id": "53",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 27,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_013",
      "cycle_id": "14",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 28,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_013",
      "cycle_id": "54",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 29,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_014",
      "cycle_id": "15",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 30,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_014",
      "cycle_id": "55",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 31,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_015",
      "cycle_id": "16",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 32,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_015",
      "cycle_id": "56",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 33,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_016",
      "cycle_id": "17",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 34,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_016",
      "cycle_id": "57",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 35,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_017",
      "cycle_id": "18",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 36,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_017",
      "cycle_id": "58",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 37,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_018",
      "cycle_id": "19",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 38,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_018",
      "cycle_id": "59",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 39,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_019",
      "cycle_id": "20",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 40,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_019",
      "cycle_id": "60",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 41,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_020",
      "cycle_id": "21",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 42,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_020",
      "cycle_id": "61",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 43,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_021",
      "cycle_id": "22",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 44,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_021",
      "cycle_id": "62",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 45,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_022",
      "cycle_id": "23",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 46,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_022",
      "cycle_id": "63",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 47,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_023",
      "cycle_id": "24",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 48,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_023",
      "cycle_id": "64",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 49,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_024",
      "cycle_id": "25",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 50,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_024",
      "cycle_id": "65",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 51,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_025",
      "cycle_id": "26",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 52,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_025",
      "cycle_id": "66",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 53,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_026",
      "cycle_id": "27",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 54,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_026",
      "cycle_id": "67",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 55,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_027",
      "cycle_id": "28",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 56,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_027",
      "cycle_id": "68",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 57,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_028",
      "cycle_id": "29",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 58,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_028",
      "cycle_id": "69",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 59,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_029",
      "cycle_id": "30",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 60,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_029",
      "cycle_id": "70",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 61,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_030",
      "cycle_id": "31",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 62,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_030",
      "cycle_id": "71",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 63,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_031",
      "cycle_id": "32",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 64,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_031",
      "cycle_id": "72",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 65,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_032",
      "cycle_id": "33",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 66,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_032",
      "cycle_id": "73",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 67,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_033",
      "cycle_id": "34",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 68,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_033",
      "cycle_id": "74",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 69,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_034",
      "cycle_id": "35",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 70,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_034",
      "cycle_id": "75",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 71,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_035",
      "cycle_id": "36",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 72,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_035",
      "cycle_id": "76",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 73,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_036",
      "cycle_id": "37",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 74,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_036",
      "cycle_id": "77",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 75,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_037",
      "cycle_id": "38",
      "start": "2021-02-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 76,
          "start": "2021-02-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_037",
      "cycle_id": "78",
      "start": "2022-02-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 77,
          "start": "2022-02-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_038",
      "cycle_id": "39",
      "start": "2021-03-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 78,
          "start": "2021-03-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_038",
      "cycle_id": "79",
      "start": "2022-03-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 79,
          "start": "2022-03-01",
          "end": "2022-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_039",
      "cycle_id": "40",
      "start": "2021-01-01",
      "end": "2021-06-30",
      "records": [
        {
          "source_row": 80,
          "start": "2021-01-01",
          "end": "2021-06-30"
        }
      ]
    },
    {
      "facility_id": "SYN_FARM_039",
      "cycle_id": "80",
      "start": "2022-01-01",
      "end": "2022-06-30",
      "records": [
        {
          "source_row": 81,
          "start": "2022-01-01",
          "end": "2022-06-30"
        }
      ]
    }
  ]
}

'''[1:-1], "\r\n", False, "17505eaac37c57bca1c40717fcca0ba2da64c6d567dcd4ec78e1ae52165ad987")

# ===== SOURCE FILE: data/examples/dsz_inseason/input/synthetic_period_definition.txt =====
_save_source("data/examples/dsz_inseason/input/synthetic_period_definition.txt", r'''
SYNTHETIC EXECUTION FIXTURE ONLY. No real farm evidence or provider confirmation.
The generator defines each DZ_004 record as the full shipment and gross revenue total
for the matching DZ_002 facility cycle, from FRMTM_BGNG_YMD through FRMTM_END_YMD.
There is exactly one management record per fictional facility cycle.

'''[1:-1], "\r\n", False, "8c8f2501472a512c08a84360c256a788116b23538275d2e458e0a743e937e380")

# ===== SOURCE FILE: data/examples/dsz_inseason/query/DZ_001.csv =====
_save_source("data/examples/dsz_inseason/query/DZ_001.csv", r'''
FRMTM_YR,FCLT_ID,MSRM_DT,INR_CO2_QTY_MRCNT,DWPNT_TMPRT_MRCNT,INR_HMDT_MRCNT,ERTH_HMDT_MRCNT,RNFAL_MRCNT,SLRDQTY_MRCNT,EXTRNL_TMPRT_MRCNT,INR_TMPRT_MRCNT,ERTH_TMPRT_MRCNT,EXTRNL_WNDDRT_MRCNT,EXTRNL_WNDSPD_MRCNT,STR_DT,STR_USERID
2025,SYN_FARM_QUERY_001,2025-01-02 08:00:00,451,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-02 16:00:00,451,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-08 08:00:00,457,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-08 16:00:00,457,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-15 08:00:00,464,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-15 16:00:00,464,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-22 08:00:00,471,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-22 16:00:00,471,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-29 08:00:00,478,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-01-29 16:00:00,478,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-02-05 08:00:00,485,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-02-05 16:00:00,485,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-03-02 08:00:00,510,,60,,,,8,18.80,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,2025-03-02 16:00:00,510,,60,,,,8,19.60,,,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "3b68b421d8e3ae4d48fe269c5b3b0b188b85dd025be3bc9237cf800aa75712ac")

# ===== SOURCE FILE: data/examples/dsz_inseason/query/DZ_002.csv =====
_save_source("data/examples/dsz_inseason/query/DZ_002.csv", r'''
FRMTM_SNO,FRMTM_YR,FCLT_ID,ITEM_NM,AREA_NM,SACT_INTLCK_SPR_NM,HTHS_SCL_CN,FRMTM_BGNG_YMD,FRMTM_END_YMD,HTHS_SFC,STR_DT,STR_USERID
9001,2025,SYN_FARM_QUERY_001,딸기,경상남도 진주시,연동,1개 동,20250101,,600,2022-08-01 10:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "f2cea50d17636e948769aabddfbefddcd757a504e41d79c355a8b97999108b96")

# ===== SOURCE FILE: data/examples/dsz_inseason/query/DZ_003.csv =====
_save_source("data/examples/dsz_inseason/query/DZ_003.csv", r'''
FRMTM_YR,FCLT_ID,EXMN_YMD,SMPL_SNO,GRDV_NOFWK,FLVS_MMUNT_MRCNT,LFLN_CMUNT_MRCNT,LFWD_CMUNT_MRCNT,ILFLN_CMUNT_MRCNT,LF_MRCNT,DMTR_MMUNT_MRCNT,SFLWR_MRCNT,FSTNG_MRCNT,LAST_FGRP_SNO,STR_DT,STR_USERID
2025,SYN_FARM_QUERY_001,20250102,1,1,92,,,,,8.15,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250102,2,1,93,,,,,8.25,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250108,1,2,98,,,,,8.45,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250108,2,2,99,,,,,8.55,,0,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250115,1,3,105,,,,,8.80,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250115,2,3,106,,,,,8.90,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250122,1,4,112,,,,,9.15,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250122,2,4,113,,,,,9.25,,1,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250129,1,5,119,,,,,9.50,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250129,2,5,120,,,,,9.60,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250205,1,6,126,,,,,9.85,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250205,2,6,127,,,,,9.95,,2,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250302,1,9,151,,,,,11.10,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
2025,SYN_FARM_QUERY_001,20250302,2,9,152,,,,,11.20,,4,,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "949e3eeb994f71675ee837eb4810ea9cfee450260442775df06909811d1c1c8d")

# ===== SOURCE FILE: data/examples/dsz_inseason/query/DZ_005.csv =====
_save_source("data/examples/dsz_inseason/query/DZ_005.csv", r'''
FCLT_ID,OBSV_PNT_CDCN,OBSV_YMD,OBSV_PNT_NM,TOP_TMPRT_MSRVL,LOWST_TMPRT_MSRVL,MAX_WNDSPD_MSRVL,DD_AVG_DWPTMP_MSRVL,STR_DT,STR_USERID
SYN_FARM_QUERY_001,SYN001,20250102,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250108,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250115,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250122,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250129,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250205,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE
SYN_FARM_QUERY_001,SYN001,20250302,합성관측소,14,3,3,2.00,2026-10-18 00:00:00,SYNTHETIC_FIXTURE

'''[1:-1], "\r\n", True, "d3b825b00baa62360bb403e30fc6c7a4ba6099ca75e6e858d3400118706c621a")

# ===== SOURCE FILE: data/examples/dsz_inseason/query/fixture_manifest.json =====
_save_source("data/examples/dsz_inseason/query/fixture_manifest.json", r'''
{
  "data_kind": "synthetic_schema_fixture",
  "purpose": "Execution only, not predictive evidence.",
  "generator": "data/examples/dsz_inseason/generate_fixture.py",
  "training_strawberry_cycles": 16,
  "query_is_unseen_synthetic_facility": true,
  "observations_are_not_fitted_to_shipment": true
}

'''[1:-1], "\r\n", False, "72c0542733c0c9ea8d796e2974f1ba34e2916e10b4259ef23740254e6d143506")

# ===== SOURCE FILE: data/examples/dsz_inseason/requests.csv =====
_save_source("data/examples/dsz_inseason/requests.csv", r'''
plan_id,facility_id,cycle_id
SYN_PLAN_001,SYN_FARM_QUERY_001,9001

'''[1:-1], "\r\n", True, "75cd9f9ddfbb9120f74a1c56fc3282c3ad99ada625ac3f6768fec957af0d1020")

# ===== SOURCE FILE: data/raw/dsz/epis_columns_user_supplied.txt =====
_save_source("data/raw/dsz/epis_columns_user_supplied.txt", r'''
# 농정원 대회용 상호제공 데이터 — 전체 컬럼 정리

사용자가 제공한 컬럼 정의 원문을 기준으로 정리했습니다. 총 11종(DZ_001~DZ_011), 컬럼 정의 132개입니다. 공통 컬럼은 각 데이터셋에서 별도로 계산했습니다.

이 문서는 데이터 구조 설명입니다. 실제 데이터 행, 결측률, 재배 품목 목록, 이미지 라벨의 실제 값은 포함하지 않습니다.

## 한눈에 보기

| ID | 데이터셋 | 내용 | 컬럼 수 |
|---|---|---|---:|
| DZ_001 | 스마트팜 우수농가 정보(환경) | 온실 내부·외부 온습도, CO2, 일사량, 강우량, 풍향·풍속 | 16 |
| DZ_002 | 스마트팜 우수농가 정보(시설) | 재배 품목, 지역, 온실 유형·규모·면적, 작기 시작·종료일 | 12 |
| DZ_003 | 스마트팜 우수농가 정보(생육) | 생육주차, 초장, 잎 길이·너비·개수, 관부직경, 꽃·열매 수 | 16 |
| DZ_004 | 스마트팜 우수농가 정보(경영조사) | 조사일별 시설의 총출하량과 총수입금액 | 7 |
| DZ_005 | 스마트팜 우수농가 정보(기상) | 관측지점별 최고·최저온도, 최대풍속, 평균 이슬점온도 | 10 |
| DZ_006 | 스마트팜 우수농가 정보(기상특보) | 기상특보 발표일시, 관측지점, 발표내용·비고 | 8 |
| DZ_007 | 스마트팜 우수농가 정보(태풍) | 태풍명, 관측일시·지점, 예상내용, 최대풍속 | 10 |
| DZ_008 | 스마트팜우수농가(토마토 9주차 이미지) | 이미지 식별정보, 크기, 부류명, 분할·경계 좌표와 면적 | 11 |
| DZ_009 | 종묘장품목주문 | 종묘 품목·품종·형태, 주문상태·수량, 파종·접목 예정일, 출하일 | 12 |
| DZ_010 | 소도체경락가격 | 소의 시장·품종·성별·등급·중량·품질과 kg당 경락가격 | 16 |
| DZ_011 | 돼지도체경락가격 | 돼지의 시장·성별·등급·중량·등지방두께와 kg당 경락가격 | 14 |

## 표를 읽는 방법

- PK1, PK2 등: 함께 사용하여 레코드를 식별하는 기본키 구성 항목입니다.
- 타입(길이): 원문의 타입과 길이를 합쳐 표기했습니다. 예: NUMBER(10,2), VARCHAR2(20).
- —: 원문 공란입니다. N/A 표기는 원문 그대로 남겼습니다.
- STR_DT는 시스템에 데이터를 적재한 일시, STR_USERID는 적재 담당 사용자 ID입니다. 실제 관측 시각·농가 ID와 구분해야 합니다.
- 온도 단위의 “도”, 일사량 단위의 “W/m-2·s” 등은 원문을 보존했습니다. 실제 분석 시 해당 단위의 정확한 의미를 확인해야 합니다.

## 데이터 간 연결

| 묶음 | 연결에 사용하는 정보 | 확인할 점 |
|---|---|---|
| 환경·시설·생육·경영·기상·기상특보·태풍 (DZ_001~007) | 시설ID(FCLT_ID), 해당 자료의 작기·측정일·조사일·관측일 | 시설ID만으로 결합하면 여러 날짜·표본이 중복될 수 있으므로 분석 단위를 먼저 맞춥니다. |
| 토마토 이미지 (DZ_008) | 작업ID·이미지ID | 정의된 컬럼에 시설ID와 촬영일시가 없어 센서자료와의 직접 연결은 확인되지 않았습니다. 부류명의 실제 라벨도 원자료에서 확인해야 합니다. |
| 종묘 주문 (DZ_009) | 주문일련번호, 품목·품종·지역·예정일·출하일 | 스마트팜 시설ID는 없습니다. 주문 접수일 컬럼도 따로 정의돼 있지 않습니다. |
| 소·돼지 경락가격 (DZ_010~011) | 경매일·시장·시도·성별·등급 등 | 서로 다른 거래 자료입니다. 축종별로 분석하고 필요하면 집계한 결과를 비교합니다. |

경영조사의 총수입금액은 비용을 뺀 순이익을 뜻하지 않습니다. 총출하량·총수입금액의 집계 기간과 누적 여부는 원자료 이용 시 확인해야 합니다.

## DZ_001 · 스마트팜 우수농가 정보(환경)

원문 실제파일명: M_DZ_SFARMENVIRONMENT · 컬럼 수: 16

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FRMTM_YR | 작기연도 | PK1 | VARCHAR2(4) | 년 | 작물의 작기시작일자의 연도 | — |
| FCLT_ID | 시설ID | PK2 | VARCHAR2(20) | N/A | 농가의 시설에 부여되는 아이디 | — |
| MSRM_DT | 측정일시 | PK3 | DATE | 일시 | 환경정보의 수집시 측정된 년월일시분초 개념의 일시 | — |
| INR_CO2_QTY_MRCNT | 내부CO2량측정결과수 | — | NUMBER(10,2) | ppm | 온실내부 이산화탄소 측정값 | — |
| DWPNT_TMPRT_MRCNT | 이슬점온도측정결과수 | — | NUMBER(10,2) | 도 | 이슬 (결로)이 형성되는 온도 | — |
| INR_HMDT_MRCNT | 내부습도측정결과수 | — | NUMBER(10,2) | ％ | 온실내부 공기 중에 포함된 수증기의 양 또는 비율 | — |
| ERTH_HMDT_MRCNT | 대지습도측정결과수 | — | NUMBER(10,2) | ％ | 대지의 공기 중에 포함된 수증기의 양 또는 비율 | — |
| RNFAL_MRCNT | 강우량측정결과수 | — | NUMBER(10,2) | mm | 강우량 측정값 | — |
| SLRDQTY_MRCNT | 일사량측정결과수 | — | NUMBER(10,2) | W/m-2·s | 태양으로부터 오는 태양 복사 에너지(일사(日射))가 지표에 닿는 양 | — |
| EXTRNL_TMPRT_MRCNT | 외부온도측정결과수 | — | NUMBER(10,2) | 도 | 온실외부 측정된 온도 값 | — |
| INR_TMPRT_MRCNT | 내부온도측정결과수 | — | NUMBER(10,2) | 도 | 온실내부 측정된 온도 값 | — |
| ERTH_TMPRT_MRCNT | 대지온도측정결과수 | — | NUMBER(10,2) | 도 | 대지의 측정된 온도 값 | — |
| EXTRNL_WNDDRT_MRCNT | 외부풍향측정결과수 | — | NUMBER(10,2) | 도 | 온실외부의 풍향 측정 값 | — |
| EXTRNL_WNDSPD_MRCNT | 외부풍속측정결과수 | — | NUMBER(10,2) | m/s | 온실외부의 풍속 측정 값 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_002 · 스마트팜 우수농가 정보(시설)

원문 실제파일명: M_DZ_SFARMFACILITY · 컬럼 수: 12

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FRMTM_SNO | 작기일련번호 | PK1 | NUMBER(13) | N/A | 작기정보 등록시 부여되는 고유일련번호 | — |
| FRMTM_YR | 작기연도 | — | VARCHAR2(4) | 년 | 작물의 작기시작일자의 연도 | — |
| FCLT_ID | 시설ID | — | VARCHAR2(20) | N/A | 농가의 시설에 부여되는 아이디 | — |
| ITEM_NM | 품목명 | — | VARCHAR2(200) | N/A | 재배하는 품목의 명칭 | — |
| AREA_NM | 지역명 | — | VARCHAR2(200) | N/A | 시설이 위치하고 있는 지역의 명칭 | — |
| SACT_INTLCK_SPR_NM | 단동연동구분명 | — | VARCHAR2(200) | N/A | 재배시설의 온실의 유형명 | — |
| HTHS_SCL_CN | 온실규모내용 | — | VARCHAR2(4000) | N/A | 온실의 규모에 대한 상세내용 | — |
| FRMTM_BGNG_YMD | 작기시작일자 | — | VARCHAR2(8) | 일 | 작물의 작기시작일자 | — |
| FRMTM_END_YMD | 작기종료일자 | — | VARCHAR2(8) | 일 | 작물의 작기종료일자 | — |
| HTHS_SFC | 온실면적 | — | NUMBER(17,3) | ㎡ | 작물을 재배하는 온실의 면적 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_003 · 스마트팜 우수농가 정보(생육)

원문 실제파일명: M_DZ_SFARMGROWTH · 컬럼 수: 16

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FRMTM_YR | 작기연도 | PK1 | VARCHAR2(4) | 년 | 작물의 작기시작일자의 연도 | — |
| FCLT_ID | 시설ID | PK2 | VARCHAR2(20) | N/A | 농가의 시설에 부여되는 아이디 | — |
| EXMN_YMD | 조사일자 | PK3 | DATE(8) | 일 | 생육정보를 조사한 일자 | — |
| SMPL_SNO | 표본일련번호 | PK4 | NUMBER(13) | N/A | 표본에 대해 부여된 번호 | — |
| GRDV_NOFWK | 생육주수 | PK5 | NUMBER(10) | 주 | 작기일에 자동으로 계산되는 해당 생육주차 | — |
| FLVS_MMUNT_MRCNT | 초장밀리미터단위측정결과수 | — | NUMBER(10,2) | mm | 지표면에서 생장점까지 (곡선)길이 | — |
| LFLN_CMUNT_MRCNT | 엽장센티미터단위측정결과수 | — | NUMBER(10,2) | cm | 맨 위에 개화 화방에서 3번째 해당하는 잎 길이(착과된 바로 위의 엽) | — |
| LFWD_CMUNT_MRCNT | 엽폭센티미터단위측정결과수 | — | NUMBER(10,2) | cm | 맨 위에 개화 화방에서 3번째 해당하는 잎의 너비 | — |
| ILFLN_CMUNT_MRCNT | 엽병장센티미터단위측정결과수 | — | NUMBER(10,2) | cm | 관부에서 초장을 측정하는 잎의 하단까지의 길이(초장-엽장) | — |
| LF_MRCNT | 엽측정결과수 | — | NUMBER(10,2) | 개 | 한 개체의 잎의 수(완전히 전개된 잎만 측정) | — |
| DMTR_MMUNT_MRCNT | 관부직경밀리미터단위측정결과수 | — | NUMBER(10,2) | mm | 원줄기 관부에서 가장 굵은 부분의 길이 | — |
| SFLWR_MRCNT | 소화측정결과수 | — | NUMBER(10,2) | 개 | 화방에 달린 꽃의 수 | — |
| FSTNG_MRCNT | 착과측정결과수 | — | NUMBER(10,2) | 개 | 화방에 달린 열매의 수(꽃잎이 떨어진 개수) | — |
| LAST_FGRP_SNO | 최종화방일련번호 | — | NUMBER(13) | 번 | 현재 개화 되어 있는 화방의 차수 기입 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_004 · 스마트팜 우수농가 정보(경영조사)

원문 실제파일명: M_DZ_SFARMMANAGEMENT · 컬럼 수: 7

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| EXMN_SNO | 조사일련번호 | PK1 | NUMBER(13) | N/A | 경영정보 등록시 부여되는 고유일련번호 | — |
| EXMN_YMD | 조사일자 | — | VARCHAR2(8) | 일 | 조사한 일자 | — |
| FCLT_ID | 시설ID | — | VARCHAR2(20) | N/A | 농가의 시설에 부여되는 아이디 | — |
| ALL_SHPMNT_KGUNT_QTY | 총출하킬로그램단위량 | — | NUMBER(20) | kg | 재배한 품목의 출하된 무게 | — |
| ALL_INCM_AMT | 총수입금액 | — | NUMBER(17,2) | 원 | 출하량에 대한 수입금액 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_005 · 스마트팜 우수농가 정보(기상)

원문 실제파일명: M_DZ_WEATHER · 컬럼 수: 10

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FCLT_ID | 시설ID | PK1 | VARCHAR2(20) | N/A | 시설 ID를 구분하는 값 | — |
| OBSV_PNT_CDCN | 관측지점코드내용 | PK2 | VARCHAR2(100) | N/A | 관측지점 코드를 구분하는 값 | — |
| OBSV_YMD | 관측일자 | PK3 | VARCHAR2(8) | 일 | 관측일자를 구분하는 값 | — |
| OBSV_PNT_NM | 관측지점명 | — | VARCHAR2(200) | 명칭 | 관측지점 명칭을 구분하는 값 | — |
| TOP_TMPRT_MSRVL | 최고온도측정값 | — | NUMBER(12) | 도 | 최고온도 측정 값 | — |
| LOWST_TMPRT_MSRVL | 최저온도측정값 | — | NUMBER(12) | 도 | 최저온도 측정 값 | — |
| MAX_WNDSPD_MSRVL | 최대풍속측정값 | — | NUMBER(12) | m/s | 최대풍속 측정 값 | — |
| DD_AVG_DWPTMP_MSRVL | 일평균이슬점온도측정값 | — | NUMBER(12) | 도 | 일평균이슬점온도 측정 값 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_006 · 스마트팜 우수농가 정보(기상특보)

원문 실제파일명: M_DZ_WEATHERNEWSBREAK · 컬럼 수: 8

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FCLT_ID | 시설ID | PK1 | VARCHAR2(20) | N/A | 시설 ID를 구분하는 값 | — |
| OBSV_PNT_CDCN | 관측지점코드내용 | PK2 | VARCHAR2(100) | N/A | 관측지점 코드를 구분하는 값 | — |
| PRSTN_DT | 발표일시 | PK3 | DATE | 일시 | 발표일시를 구분하는 값 | — |
| OBSV_PNT_NM | 관측지점명 | — | VARCHAR2(200) | N/A | 관측지점 명칭을 구분하는 값 | — |
| PRSTN_CN | 발표내용 | — | VARCHAR2(4000) | N/A | 기상특보 발표내용 | — |
| NOTE_CN | 비고내용 | — | VARCHAR2(4000) | N/A | 기상특보 비고내용 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_007 · 스마트팜 우수농가 정보(태풍)

원문 실제파일명: M_DZ_TYPHOON · 컬럼 수: 10

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| FCLT_ID | 시설ID | PK1 | VARCHAR2(20) | N/A | 시설 ID를 구분하는 값 | — |
| OBSV_PNT_CDCN | 관측지점코드내용 | PK2 | VARCHAR2(100) | N/A | 관측지점 코드를 구분하는 값 | — |
| TPHN_ENG_NM | 태풍영문명 | PK3 | VARCHAR2(200) | N/A | 태풍 영문명을 구분하는 값 | — |
| OBSV_DT | 관측일시 | PK4 | DATE | 일 | 관측일시를 구분하는 값 | — |
| OBSV_PNT_NM | 관측지점명 | — | VARCHAR2(200) | N/A | 관측지점 명칭을 구분하는 값 | — |
| TPHN_NM | 태풍명 | — | VARCHAR2(200) | N/A | 태풍 명칭을 구분하는 값 | — |
| TPHN_EXPCT_CN | 태풍예상내용 | — | VARCHAR2(4000) | N/A | 태풍 예상내용을 나타내는 값 | — |
| MAX_WNDSPD_MSRVL | 최대풍속측정값 | — | NUMBER(12) | m/s | 최대풍속 측정값 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_008 · 스마트팜우수농가(토마토 9주차 이미지)

원문 실제파일명: M_DZ_ITEMIMAGE · 컬럼 수: 11

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| JOB_ID | 작업ID | PK1 | VARCHAR2(20) | — | 작업 ID를 구분하는 값 | — |
| IMG_ID | 이미지ID | PK2 | VARCHAR2(20) | — | 이미지 ID를 구분하는 값 | — |
| IMG_FILE_NM | 이미지파일명 | — | VARCHAR2(200) | — | 이미지 파일명을 구분하는 값 | — |
| IMG_WIDTH_LEN | 이미지가로길이 | — | NUMBER(10) | — | 이미지 가로길이를 나타내는 값 | — |
| IMG_VRTCL_LEN | 이미지세로길이 | — | NUMBER(10) | — | 이미지 세로길이를 나타내는 값 | — |
| CLSSF_NM | 부류명 | — | VARCHAR2(200) | — | 부류명을 구분하는 값 | — |
| IMG_DVSN_CRDNT_CN | 이미지분할좌표내용 | — | VARCHAR2(4000) | — | 이미지 분할좌표 내용을 나타내는 값 | — |
| IMG_BNDRY_CRDNT_CN | 이미지경계좌표내용 | — | VARCHAR2(4000) | — | 이미지 경계좌표 내용을 나타내는 값 | — |
| IMG_DVSN_CRDNT_SFC | 이미지분할좌표면적 | — | NUMBER(17) | — | 이미지 분할좌표 면적을 나타내는 값 | — |
| STR_DT | 적재일시 | — | DATE | — | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | — | 데이터 적재사용자 ID | — |

## DZ_009 · 종묘장품목주문

원문 실제파일명: M_DZ_NURSERYITEMORDER · 컬럼 수: 12

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| NRSRY_ITEM_PORDR_SNO | 종묘장품목주문일련번호 | PK1 | NUMBER(6) | N/A | 주문정보 등록시 부여되는 고유일련번호 | — |
| NRSRY_CTPRVN_NM | 종묘장시도명 | — | VARCHAR2(10) | N/A | 출하 지역 시도명 | — |
| NRSRY_CTNDCT_NM | 종묘장시군구명 | — | VARCHAR2(20) | N/A | 출하 지역 시군구명 | — |
| RSDNG_PORDR_SPR_NM | 종묘주문구분명 | — | VARCHAR2(10) | N/A | 주문 종묘의 형태(일반/실생/접목) | — |
| RSDNG_PORDR_STAT_NM | 종묘주문상태명 | — | VARCHAR2(10) | N/A | 주문 종묘의 출하 상태 | — |
| RSDNG_PORDR_VRTY_NM | 종묘주문품종명 | — | VARCHAR2(10) | N/A | 주문 종묘의 품종명 | — |
| RSDNG_PORDR_ITEM_NM | 종묘주문품목명 | — | VARCHAR2(20) | N/A | 주문 종묘의 세부 품목명 | — |
| RSDNG_PORDR_QY | 종묘주문수량 | — | NUMBER(10) | 개 | 주문 종묘 수량 | — |
| SOWNG_GRFT_SCHDL_YMD | 파종접목예정일자 | — | VARCHAR2(8) | 일 | 주문 종묘의 파종 예정 일자 | — |
| SHPMNT_YMD | 출하일자 | — | VARCHAR2(8) | 일 | 주문 종묘의 출하 일자 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_010 · 소도체경락가격

원문 실제파일명: M_DZ_COWBIDDINGPRICE · 컬럼 수: 16

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| COW_ACTNG_PRC_MNGNO | 소경락가격관리번호 | PK1 | VARCHAR2(12) | N/A | 소 경락가격의 고유 관리번호 | — |
| AUCTN_YMD | 경매일자 | — | VARCHAR2(8) | 일 | 경매일자를 나타내는 값 | — |
| WHLSL_MRKT_NM | 도매시장명 | — | VARCHAR2(200) | 명칭 | 도매시장명을 나타내는 값 | — |
| CTPRVN_NM | 시도명 | — | VARCHAR2(200) | N/A | 시도명을 나타내는 값 | — |
| WHLSL_MRKT_ADDR | 도매시장주소 | — | VARCHAR2(500) | N/A | 도매시장주소를 나타내는 값 | — |
| VRTY_NM | 품종명 | — | VARCHAR2(200) | N/A | 품종명을 나타내는 값 | — |
| GNDR_NM | 성별명 | — | VARCHAR2(200) | N/A | 성별명을 나타내는 값 | — |
| MTQLTY_GRD_NM | 육질등급명 | — | VARCHAR2(200) | 등급 | 육질등급명을 나타내는 값 | — |
| MTQTY_GRD_NM | 육량등급명 | — | VARCHAR2(200) | 등급 | 육량등급명을 나타내는 값 | — |
| BCKFT_THCKNS_LEN | 등지방두께길이 | — | NUMBER(10,2) | mm | 등지방두께길이를 나타내는 값 | — |
| COW_DRSWGT | 소도체중 | — | NUMBER(12,2) | kg | 소도체중을 나타내는 값 | — |
| SRLN_CRSCTN_SFC | 등심단면면적 | — | NUMBER(17,3) | cm^2 | 등심단면면적을 나타내는 값 | — |
| MBSCR_CNT | 근내지방도수 | — | NUMBER(10) | 등급 | 근내지방도수를 나타내는 값 | — |
| ACTNG_PKG_AMT | 경락킬로그램당금액 | — | NUMBER(17,2) | 원 | 경락킬로그램당금액을 나타내는 값 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | N/A | 데이터 적재사용자 ID | — |

## DZ_011 · 돼지도체경락가격

원문 실제파일명: M_DZ_PIGBIDDINGPRICE · 컬럼 수: 14

| 영문 컬럼 | 한글명 | 키 | 타입(길이) | 단위 | 설명 | 비고 |
|---|---|---|---|---|---|---|
| PG_ACTNG_PRC_MNGNO | 돼지경락가격관리번호 | PK1 | VARCHAR2(12) | N/A | 돼지 경락가격의 고유 관리번호 | — |
| AUCTN_YMD | 경매일자 | — | VARCHAR2(8) | 일 | 경매일자를 나타내는 값 | — |
| WHLSL_MRKT_NM | 도매시장명 | — | VARCHAR2(200) | 명칭 | 도매시장명을 나타내는 값 | — |
| CTPRVN_NM | 시도명 | — | VARCHAR2(200) | N/A | 시도명을 나타내는 값 | — |
| WHLSL_MRKT_ADDR | 도매시장주소 | — | VARCHAR2(500) | N/A | 도매시장주소를 나타내는 값 | — |
| BTLVSTCK_SPR_CD | 도체구분명 | — | VARCHAR2(200) | N/A | 도체구분명을 나타내는 값 | — |
| PGSKN_SPR_CD | 돈피구분명 | — | VARCHAR2(200) | N/A | 돈피구분명을 나타내는 값 | — |
| GNDR_NM | 성별명 | — | VARCHAR2(200) | N/A | 성별명을 나타내는 값 | — |
| LAST_GRD_NM | 최종등급명 | — | VARCHAR2(200) | 등급 | 최종등급명을 나타내는 값 | — |
| BCKFT_THCKNS_LEN | 등지방두께길이 | — | NUMBER(10,2) | mm | 등지방두께길이를 나타내는 값 | — |
| PG_DRSWGT | 돼지도체중 | — | NUMBER(12,2) | kg | 돼지도체중을 나타내는 값 | — |
| ACTNG_PKG_AMT | 경락킬로그램당금액 | — | NUMBER(17,2) | 원 | 경락킬로그램당금액을 나타내는 값 | — |
| STR_DT | 적재일시 | — | DATE | 일시 | 데이터 적재일시 | — |
| STR_USERID | 적재사용자ID | — | VARCHAR2(20) | N/A | 데이터 적재사용자 ID | — |

출처: 사용자가 첨부한 농림수산식품교육문화정보원 데이터 컬럼 정의 텍스트.

'''[1:-1], "\n", False, "fcbf6d647b64686775e847d575ed4e8bc9bb3b79b958f54c95dfe7289e09faff")

# ===== SOURCE FILE: reports/dsz_csv_format.md =====
_save_source("reports/dsz_csv_format.md", r'''
# 실제 CSV 파일명과 읽기 형식

근거: 농림수산식품교육문화정보원_데이터정의서.zip 내부 XLSX의 '미개방데이터셋 목록' 시트 G3:G9(파일명), K열(인용부호), M열(인코딩) 및 구분자 열.
ZIP SHA256: 33842ba16d497cae95d1ff1392779a6dfae00a30dd4a17dfe1154e246c3e34f0

| ID | 명세서의 CSV 전체 파일명 | 구분자 |
|---|---|---|
| DZ_001 | 스마트팜 우수농가 정보(환경)(M_DZ_SFARMENVIRONMENT).csv | 파이프(\|) |
| DZ_002 | 스마트팜 우수농가 정보(시설)(M_DZ_SFARMFACILITY).csv | 파이프(\|) |
| DZ_003 | 스마트팜 우수농가 정보(생육)(M_DZ_SFARMGROWTH).csv | 파이프(\|) |
| DZ_004 | 스마트팜 우수농가 정보(경영조사)(M_DZ_SFARMMANAGEINQUIRY).csv | 파이프(\|) |
| DZ_005 | 스마트팜 우수농가 정보(기상)(M_DZ_WEATHER).csv | 파이프(\|) |
| DZ_006 | 스마트팜 우수농가 정보(기상특보)(M_DZ_WEATHERNEWSBREAK).csv | 쉼표(,) |
| DZ_007 | 스마트팜 우수농가 정보(태풍)(M_DZ_TYPHOON).csv | 파이프(\|) |

모두 UTF-8, 인용부호 사용 FALSE. 경영조사는 목록 시트의 SFARMMANAGEINQUIRY와 컬럼 정의 시트의 SFARMMANAGEMENT가 다르므로 둘 다 명시적으로 지원합니다. 실제 원자료를 받은 뒤 열과 내용을 검사해야 합니다.

단일 실행 파일 smartfarm_shipment.py와 같은 내용의 반입용 TXT를 사용합니다. 파일 상단에 과거 원자료 폴더·예측 대상 폴더(선택)·시설ID·작기ID를 입력하면 자동으로 요청 CSV를 만듭니다. 파일명은 정확한 명세 이름 또는 DZ_00N/영문 식별자여야 하며, 같은 표가 두 파일이면 오류입니다. 하위 폴더나 분할 CSV 자동 병합은 하지 않습니다.

실제 집계기간 근거가 없으면 검사만 진행합니다. 출하량 예측은 검증 가능한 정답이 있는 과거 작기로 학습한 후 수행합니다. 이 배포물의 실행 확인은 합성 데이터로만 했으며 실제 연결률·예측 정확도는 현장에서 확인해야 합니다.

'''[1:-1], "\n", False, "d1758dac77a238ab49c3866a02f55d5df37d88e217cb4091967a3847aa5e36c5")

# ===== SOURCE FILE: reports/dsz_inseason_guide.md =====
_save_source("reports/dsz_inseason_guide.md", r'''
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

'''[1:-1], "\n", False, "3273ebe90d7c47950e4ec2dcfa1d9a405e96fb28976a5a89d61a6ac1ab62cfa3")

# ===== SOURCE FILE: reports/dsz_model_method.md =====
_save_source("reports/dsz_model_method.md", r'''
# DSZ 명세 기반 오프라인 모델 실행법

이 문서는 기존 재배 전 7개 입력 경로다. 새 `scripts/run_dsz_inseason.py`는 기본 7개와 과거 관측을 추가한 입력을 동일 검증 대상에서 비교한다. [재배 중 출하량 예측 안내](dsz_inseason_guide.md)에 파일·명령·결과를 정리했다. 기간 확인은 두 경로 모두 필요하다.

이 경로는 미개방 원자료의 명세에 맞춰 준비한 코드를 현장에서 실제 파일로 실행하기 위한 것이다. `synthetic_schema_fixture`는 **코드 실행을 확인하는 가상 자료**이며, 점수·예측은 실제 농가 성능을 뜻하지 않는다. 실제 자료는 준비 단계에서 `onsite_private_unverified`로 구별하며 집계 가정이 확인되기 전에는 인증된 작기 총량이라고 표현하지 않는다.

## 입력과 타깃

`prepare_dsz.py`가 생성하는 `dsz_model_candidates.csv`와 `dsz_manifest.json`을 입력한다. 모델은 CSV의 SHA, 출처 태그, 특성 계약을 검사한다. 정확히 다음 7개 계획 특성만 사용한다.

`crop, region, greenhouse_type, greenhouse_size, area_m2, planned_start_year, planned_start_month`

면적은 ㎡이며 양수여야 한다. 실제 종료일, 관측 환경·생육, 경영 수치, 시설ID, 작기ID는 입력하지 않는다. 시설ID는 검증 분리에만 사용한다. 출하량 kg와 총수입 원은 각각 유효한 행으로 독립 학습하며, 한쪽 결측 때문에 다른 타깃을 지우지 않는다. 명시적으로 관측된 0은 보존하고 결측을 0으로 대체하지 않는다.

기본 `single_record_per_cycle`은 정확히 하나의 경영 기록이 작기에 연결된 후보를 만든다. **단일행이라는 이유만으로 전체 작기 총량으로 학습하지 않는다.** 준비 단계에 `--period-confirmation`으로 문서·원본 해시·집계 방식·행별 기간 확인 기록을 제공해야 한다. 확인되지 않은 후보는 감사 전용이며 학습·예측·경제성 연결 경계에서 차단한다. 선택 정책과 확인 근거는 모델·예측 출처 기록으로 전파된다. 이는 문서에 근거한 검토 기록이며 기관의 독립 검증이나 연간 환산을 자동 보증하지 않는다. 총수입은 순이익이 아니다.

## CPU 비교와 예측

시설 수에 따라 GroupKFold 2~5개를 사용하며, 같은 시설의 작기는 한 폴드에 함께 둔다. 특정 타깃의 시설이 2개 미만이면 그 타깃만 `skipped_insufficient_data`로 기록하며 다른 타깃은 계속 학습한다. 두 타깃 모두 부족할 때는 실패한다. 품목 중앙값, 학습 자료의 품목별 kg/㎡ 또는 원/㎡ 중앙값×계획면적, CatBoost(MAE), XGBoost(absolute error)를 같은 타깃 행·폴드에서 비교한다. 범주 변환과 기준선은 학습 폴드만 사용한다. 학습 정답이 상수(전부 0 포함)이거나 모든 학습 특성이 상수인 폴드는 두 ML 방법을 학습 중앙값으로 대체하고 이유·폴드·방법을 감사 기록에 남긴다. 이 판단에는 검증 정답을 사용하지 않는다. 검증에만 있는 품목은 OOF에서 표시하며, 실제 계획 예측은 학습에 없던 품목을 거부한다.

OOF MAE가 가장 작은 CPU 방법을 전체 유효행에 다시 적합해 로컬 joblib 파일에 저장한다. 선택에 사용한 OOF는 독립된 최종 검증셋이 아니며 미래 연도·장비 도입의 인과 효과·투자회수기간을 검증하지 않는다. 예측기는 우리가 생성한 신뢰할 수 있는 로컬 파일만 대상으로 하고, 불러오기 전에 선언된 SHA를 확인한다. 외부인이 제공한 pickle/joblib을 받아 실행하는 기능이 아니다.

```powershell
python scripts/train_dsz.py --data-dir data/examples/dsz/processed --output-dir artifacts/dsz_demo
python scripts/predict_dsz.py --artifact-dir artifacts/dsz_demo --plans data/examples/dsz/example_plans.csv --output artifacts/dsz_demo/example_predictions.csv
```

현장에서는 `--data-dir`, `--output-dir`, `--plans`, `--output`을 실제 자료와 현장 결과 폴더로 지정한다. 네트워크·서버·외부 API를 사용하지 않는다. `dsz_model_metrics.json`, 타깃별 OOF, 모델 파일, 실행 보고서에 데이터 종류와 출처가 남는다. 예측 CSV와 `.provenance.json`에도 가상/실제 입력 출처가 전파된다.

## 선택적인 LimiX

기본 CPU 번들은 LimiX 코드·가중치·CUDA가 없어도 동작한다. 사전에 허용된 GPU와 이미 설치·검증한 공식 400M 체크포인트가 있는 전체 작업환경에서만 `--include-limix --limix-python .venv-limix/Scripts/python.exe`로 별도 비교를 실행한다. 코드를 지연 import하고 누락된 환경은 명확히 오류로 처리하며 다운로드하거나 다른 모델로 대체하지 않는다.

이 추가 비교는 동일 시설 폴드·행을 사용하고 실제 V2 회귀 전처리와 내부 정규화의 학습행 불변성을 검사한다. 고정된 사전학습 가중치를 사용하며, 기본 CPU 배포 모델 선택은 바꾸지 않는다. 추가 점수와 OOF는 `dsz_limix_comparison.json`, `dsz_*_limix_oof.csv`에 별도로 저장된다. 가상 자료로 실행한 LimiX 점수 역시 실행 검증에 한정된다.

'''[1:-1], "\n", False, "9acc91c07bc9d4a146575dd00460a86abc08b16e85f787f265910a9eeced7e13")

# ===== SOURCE FILE: reports/dsz_onsite_guide.md =====
_save_source("reports/dsz_onsite_guide.md", r'''
# 농정원 미개방 데이터 — 현장 실행 안내

사용자가 대구 데이터안심구역을 방문했으며 원자료는 현장에서만 볼 수 있다고 확인했다. 이에 **명세서에 맞춰 실행 코드를 완성하고 현장에서 실제 파일을 넣어 실행하는 방식**으로 준비했다. 동봉한 농가 CSV는 모두 인위적으로 만든 예제다. 실제 미개방 원자료·계정·API 키는 들어 있지 않다.

## 이 패키지가 하는 일

시설·경영조사 파일 검사 → 시설ID와 조사일로 연결 후보 생성 → **집계기간·방식을 근거 문서와 원본 행에 대조** → 확인된 출하량과 매출을 각각 시설별 교차검증 → CPU 모델 선택·저장 → 새 계획 조건의 예측 CSV 생성. 기간 근거가 없으면 후보 감사까지 수행하며 학습하지 않는다.

- 출하량: 정의서의 `ALL_SHPMNT_KGUNT_QTY`, **kg**.
- 매출: 정의서의 `ALL_INCM_AMT`, **원**. 비용을 뺀 순이익이 아니다.
- 입력: 품목, 지역, 단동/연동, 온실 규모 설명, 면적(㎡), 계획 시작 연도·월.
- 비교: 품목 중앙값, 면적당 품목 중앙값, CatBoost, XGBoost.
- 같은 시설은 학습·검증에 겹치지 않는다. 후보 선택에 사용한 교차검증 점수이므로 독립적인 최종 검증이나 미래연도 정확도를 뜻하지 않는다.

위 설명은 재배 전 7개 입력 경로다. **재배 중에는 `run_dsz.ps1 -InSeason`으로 환경·생육·기상과 발표된 특보 기록을 같은 시설·작기에 연결할 수 있다.** [재배 중 입력·실행·검증 안내](dsz_inseason_guide.md)를 따른다. 태풍은 발표시점 확인이 없어 검사만 한다. 재배 후에 생기는 값은 도입 전 예측 입력으로 넣지 않으며, 종묘 주문·축산물·사진을 시설ID로 억지로 연결하지 않는다.

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

근거가 없을 때는 시설ID가 같고 조사일이 작기 시작·종료일 사이에 포함되는 **정확히 한 작기**의 감사 후보만 만든다. 학습에는 아래 확인 JSON의 **원본 조사행→시설·작기 매핑과 집계기간**을 사용한다. 작기 종료 뒤 조사한 정산도 매핑과 기간이 확인되면 처리할 수 있다. 시설ID 불일치·중복 매핑·잘못된 기간에는 제외 사유를 남긴다. 적재일시는 조사일 대신 사용하지 않는다. 숫자형 식별자도 문자열로 보존한다.

### 경영조사 집계 방식은 실제 자료 의미에 맞춰 선택

정의서는 kg·원 단위는 명시하지만 각 조사행이 누계인지 증분인지, 어느 기간을 집계했는지는 명시하지 않는다. **`-ManagementPolicy` 선택만으로 학습할 수 없다.** 실제 원자료의 정의를 확인한 문서와 검토 기록을 `-PeriodConfirmation` JSON으로 함께 제공한다. 원문 명세서에 없는 집계 정의를 있다고 작성하면 안 된다.

| `-ManagementPolicy` | 사용할 상황 | 처리 |
|---|---|---|
| `single_record_per_cycle` (기본) | 한 기록이 전체 작기의 총량이라는 정의가 확인됨 | 그 행의 집계 시작·끝이 작기 전체와 같아야 함 |
| `incremental_sum` | 각 조사행이 중복되지 않는 기간의 증분이라는 정의가 확인됨 | 명시된 기간이 겹침·공백 없이 작기 전체를 덮어야 함. 결측을 부분합으로 대체하지 않음 |
| `latest_cumulative` | 각 행이 작기 시작부터의 누계라는 정의가 확인됨 | 가장 늦은 조사행이 작기 말까지의 최종 누계임을 확인. 중복 최종행은 제외 |

확인 JSON에는 원본 시설·경영 파일명과 SHA256, 실제 정의 근거 파일과 SHA256·페이지/항목·검토자·검토일·집계 정의, 시설/작기별 집계 시작·끝과 원본 조사행 번호가 필요하다. 상세 필드는 `dsz_schema_contract.md`를 따른다. 코드는 파일 일치와 기간 구조를 검사하며, 문서 내용의 의미까지 자동으로 심사하거나 기관 확인을 대신하지 않는다. 값 0은 관측값으로 남기고 결측을 0으로 채우지 않으며, 출하량·매출의 수치 유효성과 학습 적격성을 구분한다.

새 농가 계획은 동봉 `data\examples\dsz\example_plans.csv`의 헤더를 복사해 실제 계획값으로 작성한다. 품목·지역·시설 표기는 실제 학습 데이터 표기와 맞춘다. 학습에 전혀 없던 품목은 예측하지 않는다.

```powershell
.\run_dsz.ps1 -InputDir 'D:\approved_work\farm_data' `
  -Plans 'D:\approved_work\plans.csv' `
  -PeriodConfirmation 'D:\approved_work\period_confirmation.json' `
  -ManagementPolicy single_record_per_cycle

# CP949 CSV이면 -Encoding cp949 추가
```

명령별 실행 또는 Windows 이외 환경의 설치된 Python 사용:

```text
python scripts/prepare_dsz.py --input-dir /approved/farm_data --output-dir runs/onsite/prepared --management-policy single_record_per_cycle --period-confirmation /approved/period_confirmation.json
python scripts/train_dsz.py --data-dir runs/onsite/prepared --output-dir runs/onsite/models
python scripts/predict_dsz.py --artifact-dir runs/onsite/models --plans /approved/plans.csv --output runs/onsite/predictions.csv
```

집계기간을 확인하지 못했다면 `prepare_dsz.py`만 `--period-confirmation` 없이 실행한다. 후보와 제외 사유는 남지만 학습 적격은 false다. 그 결과를 `train_dsz.py`에 넘기거나 예측의 연 1작기 적용에 동의해도 기간 미확정을 우회할 수 없다. 확인 자료는 현장 규정에 따라 그 안에서 보관한다.

일부 작기만 확인할 수 있었다면 미확정 후보는 감사용으로 남기고 확인된 적격 작기만 사용한다. 모델 출처 기록의 `training_cohort`에서 사용·제외 수와 행 목록을 확인한다. 한 작기의 확인 근거를 같은 시설의 다른 작기에 자동 적용하지 않는다.

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

'''[1:-1], "\n", False, "74d03a8498aafb3936f14afcb95c28560521c2d87d0bf84af6d1d1c3fbb0ee2c")

# ===== SOURCE FILE: reports/dsz_schema_contract.md =====
_save_source("reports/dsz_schema_contract.md", r'''
# 대회 미개방 데이터: 명세서 기반 현장 실행 계약

사용자가 대구 안심구역 방문을 완료했으며 실제 데이터는 현장 안에서만 볼 수 있다고 설명했다. 이에 실제 파일이 들어올 경로와 전처리·모델 입력을 명세서대로 구현한다. 이 문서와 예제는 미개방 원자료를 외부에서 확보했거나 실제 데이터의 정확도를 검증했다는 증거가 아니다.

## 입력과 형식

원문은 `data/raw/dsz/epis_columns_user_supplied.txt`이며 `config/dsz_schema.json`에 DZ_001~007의 영문 컬럼명, Oracle 타입·길이, 키, 단위를 그대로 옮겼다. 경영 총출하량은 `NUMBER(20)` kg, 총수입은 `NUMBER(17,2)` 원, 시설면적은 `NUMBER(17,3)` ㎡다. 타입을 보고 표본 수·결측률·실제 품목 분포를 추정하지 않는다.

| 자료 | 입력 여부 | 이번 서비스 사용 |
|---|---|---|
| DZ_002 시설 | 필수 | 작기·시설 식별, 사전 계획 특성 |
| DZ_004 경영조사 | 필수 | 조사 기록의 출하량·매출 후보 목표값 |
| DZ_001 환경 / DZ_003 생육 | 선택 | 기본 경로는 검사만, 재배 중 경로는 과거 관측 요약 |
| DZ_005 기상 / DZ_006 특보 | 선택 | 기본 경로는 검사만, 재배 중 경로는 과거 기상·발표 행 수 |
| DZ_007 태풍 | 선택 | 검사·목록만. 당시 발표시점 확인 없이 예측 입력으로 사용하지 않음 |
| DZ_008 이미지 / DZ_009 종묘 / DZ_010·011 축산 | 이 서비스의 입력에서 제외 | 앞의 두 자료에는 시설ID 연결 키가 없고 축산은 작물 도입 분석과 별도 거래 자료 |

각 파일은 `DZ_002.csv` 또는 원문 이름 `M_DZ_SFARMFACILITY.csv`처럼 제공한다. `.xlsx`도 허용하며 데이터셋당 한 시트다. 확장자·파일명 대소문자는 구분하지 않고 컬럼명은 정확히 일치해야 한다. 같은 데이터셋 파일을 두 개 주면 임의로 고르지 않고 오류를 낸다. UTF-8 BOM CSV가 기본이며 CP949는 `--encoding cp949`로 명시한다.

읽을 때 모든 원문 값을 문자열로 유지해 `00017` 같은 ID와 `NA` 같은 텍스트를 보존한다. XLSX에서 ID 자체가 텍스트로 저장되어야 선행 0을 보존할 수 있다. Excel 숫자 저장 단계에서 이미 유실된 0이나 정밀도를 복원하지 않는다. 원문의 VARCHAR2(8) 날짜는 YYYYMMDD를 요구하며 Oracle DATE는 YYYYMMDD, YYYY-MM-DD, 초 단위 ISO 시각 등 구현에 명시된 형식을 검증한다. 필수 파일의 모든 정의 컬럼은 있어야 하며 비키 값은 공란을 허용하되 모델에 필요한 값은 별도로 판정한다.

## 결합과 목표값

재배 중 관측의 별도 입력 계약과 실행법은 [재배 중 안내](dsz_inseason_guide.md)를 따른다. 아래 기간 확인 규칙은 두 경로의 학습 정답에 공통 적용한다.

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

'''[1:-1], "\n", False, "ccba57617c9b27f204c6a15c3471c0abed0299e5b66aadbd3a8cf6fb8282a5a8")

# ===== SOURCE FILE: requirements-dsz-cpu.txt =====
_save_source("requirements-dsz-cpu.txt", r'''
numpy==2.3.5
pandas==3.0.1
scikit-learn==1.9.1
catboost==1.2.10
xgboost==3.4.1
openpyxl==3.1.5
joblib==1.6.0

'''[1:-1], "\n", False, "a2d809fd3773ddc919530adfa7c6f11e1b1acf2ddb500a6761a350aa4077fbb5")

# ===== SOURCE FILE: scripts/predict_dsz.py =====
_save_source("scripts/predict_dsz.py", r'''
"""Predict plans with trusted locally generated DSZ artifacts; preserve provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import pandas as pd  # noqa: E402

from src.dsz_model import CATEGORICAL, NUMERIC, predict_plans, sha256  # noqa: E402
from src.dsz_period import require_model_confirmation  # noqa: E402


def predict_from_artifacts(artifact_dir: Path, plans: pd.DataFrame) -> pd.DataFrame:
    """Only call on this pipeline's trusted local files, never uploaded pickle files."""
    manifest = json.loads((artifact_dir / "dsz_model_metrics.json").read_text(encoding="utf-8"))
    if manifest["status"] != "completed":
        raise ValueError("Training run is not completed")
    require_model_confirmation(manifest)
    for name in ["src/dsz_model.py", "src/dsz_period.py", "scripts/predict_dsz.py"]:
        if manifest.get("source_sha256", {}).get(name) != sha256(ROOT / name):
            raise ValueError(f"Current prediction source differs from training run: {name}")
    predictions = []
    for target, record in manifest["targets"].items():
        if record["status"] != "completed":
            continue
        path = artifact_dir / record["artifact_file"]
        if path.resolve().parent != artifact_dir.resolve() or sha256(path) != record["artifact_sha256"]:
            raise ValueError("Generated model artifact path/SHA differs from manifest")
        bundle = joblib.load(path)
        for key in ["data_kind", "target_assumption", "target_period_confirmed", "source_manifest_sha256",
                    "target_period_evidence_sha256", "target_period_confirmation", "training_cohort",
                    "training_cohort_sha256", "candidate_sha256"]:
            if bundle[key] != manifest[key]:
                raise ValueError("Model/provenance mismatch")
        if bundle["target"] != target:
            raise ValueError("Artifact target mismatch")
        predictions.append(predict_plans(bundle, plans))
    if not predictions:
        raise ValueError("No trained targets")
    return pd.concat(predictions, ignore_index=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True, help="Trusted artifacts generated by train_dsz.py")
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plans = pd.read_csv(args.plans, encoding="utf-8-sig", keep_default_na=False,
                        dtype={name: str for name in CATEGORICAL + ["plan_id"]},
                        na_values={name: [""] for name in NUMERIC})
    result = predict_from_artifacts(args.artifact_dir, plans)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    training_manifest = json.loads((args.artifact_dir / "dsz_model_metrics.json").read_text(encoding="utf-8"))
    metadata = {"data_kind": result["data_kind"].unique().tolist(),
                "target_assumption": result["target_assumption"].unique().tolist(),
                "target_period_confirmed": result["target_period_confirmed"].unique().tolist(),
                "target_period_evidence_sha256": training_manifest["target_period_evidence_sha256"],
                "target_period_confirmation": training_manifest["target_period_confirmation"],
                "training_cohort": training_manifest["training_cohort"],
                "training_cohort_sha256": training_manifest["training_cohort_sha256"],
                "training_manifest_sha256": sha256(args.artifact_dir / "dsz_model_metrics.json"),
                "plans_sha256": sha256(args.plans), "prediction_sha256": sha256(args.output),
                "rows": len(result), "interpretation": result["interpretation"].unique().tolist()}
    args.output.with_suffix(".provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))

'''[1:-1], "\n", False, "7ef0af587c8411b141143aa6ceca67d33f1788f8ddac09a7e909a3d54078cbc2")

# ===== SOURCE FILE: scripts/prepare_dsz.py =====
_save_source("scripts/prepare_dsz.py", r'''
"""Run local DSZ schema preparation with no network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dsz_data import MANAGEMENT_POLICIES, prepare  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    parser.add_argument("--management-policy", choices=MANAGEMENT_POLICIES, default="single_record_per_cycle")
    parser.add_argument("--period-confirmation", type=Path, help="Document-backed per-cycle period declaration JSON; absent means audit-only")
    args = parser.parse_args()
    manifest = prepare(args.input_dir, args.output_dir, encoding=args.encoding,
                       management_policy=args.management_policy, period_confirmation=args.period_confirmation)
    print(json.dumps({key: manifest[key] for key in ["data_kind", "candidate_rows", "target_eligible_rows", "target_assumption"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

'''[1:-1], "\n", False, "9e8bf8f3d3993d8ce8cfd7950f225013775a922204d5f06d67fa5257caa6d43d")

# ===== SOURCE FILE: scripts/run_dsz_inseason.py =====
_save_source("scripts/run_dsz_inseason.py", r'''
"""Train or predict fixed-cutoff DSZ shipment updates entirely offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.dsz_inseason import predict_inseason, train_inseason, write_json  # noqa: E402
from src.dsz_model import sha256  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="Compare seven planned inputs with same-cohort observation features")
    train.add_argument("--data-dir", type=Path, required=True, help="Prepared data with documented target periods")
    train.add_argument("--input-dir", type=Path, required=True, help="The exact raw export used for preparation")
    train.add_argument("--output-dir", type=Path, required=True, help="New directory; existing output is never overwritten")
    train.add_argument("--cutoff-days", type=int, default=30)
    train.add_argument("--window-days", type=int, default=28)
    train.add_argument("--crop", default="딸기")
    train.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    predict = sub.add_parser("predict", help="Use trusted locally generated model artifacts")
    predict.add_argument("--artifact-dir", type=Path, required=True)
    predict.add_argument("--input-dir", type=Path, required=True, help="Query facility and observation tables; management optional")
    predict.add_argument("--requests", type=Path, required=True, help="CSV containing plan_id,facility_id,cycle_id only")
    predict.add_argument("--output", type=Path, required=True)
    predict.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    args = parser.parse_args()
    if args.command == "train":
        result = train_inseason(args.data_dir, args.input_dir, args.output_dir, cutoff_days=args.cutoff_days,
                               window_days=args.window_days, crop=args.crop, encoding=args.encoding)
        print(json.dumps({key: result[key] for key in ["status", "data_kind", "rows", "facilities", "selected_methods"]}, ensure_ascii=False))
    else:
        metadata_path = args.output.with_suffix(".provenance.json")
        if args.output.exists() or metadata_path.exists():
            raise FileExistsError("Prediction or provenance output exists; choose a new output path")
        requests = pd.read_csv(args.requests, encoding=args.encoding, dtype=str, keep_default_na=False)
        result, metadata = predict_inseason(args.artifact_dir, args.input_dir, requests, encoding=args.encoding)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        metadata.update(requests_sha256=sha256(args.requests), prediction_sha256=sha256(args.output), rows=len(result))
        write_json(metadata_path, metadata)
        print(json.dumps({"status": "completed", "rows": len(result), "data_kind": metadata["data_kind"],
                          "output": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()

'''[1:-1], "\n", False, "690331850b032068062c478cfa4894789fd03023e5be06dddb6292477a4afc58")

# ===== SOURCE FILE: scripts/train_dsz.py =====
_save_source("scripts/train_dsz.py", r'''
"""Train offline DSZ schema candidates; synthetic scores prove execution only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

for variable in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[variable] = "2"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.dsz_model import CATEGORICAL, FEATURES, NUMERIC, TARGETS, features, fit_target, grouped_folds, prepare_target, scores, sha256  # noqa: E402
from src.dsz_period import evidence_digest, require_confirmed_rows, require_model_confirmation  # noqa: E402


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_data(data_dir):
    manifest_path = data_dir / "dsz_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = manifest["artifacts"]["candidates"]
    path = data_dir / candidate["file"]
    if path.resolve().parent != data_dir.resolve() or sha256(path) != candidate["sha256"]:
        raise ValueError("Candidate path or SHA differs from preparation manifest")
    if manifest["features"] != FEATURES:
        raise ValueError("Preparation/model feature contracts differ")
    string_columns = CATEGORICAL + ["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]
    numeric_columns = NUMERIC + [value[0] for value in TARGETS.values()]
    rows = pd.read_csv(path, encoding="utf-8-sig", dtype={name: str for name in string_columns},
                       keep_default_na=False, na_values={name: [""] for name in numeric_columns})
    data_kind = manifest["data_kind"]
    if data_kind not in {"synthetic_schema_fixture", "onsite_private_unverified"}:
        raise ValueError("Unknown data_kind")
    for name in ["data_kind", "target_assumption"]:
        if not rows[name].eq(manifest[name]).all():
            raise ValueError(f"Candidate/manifest provenance mismatch: {name}")
    if "target_period_confirmed" not in rows or not rows.target_period_confirmed.isin([True, False]).all():
        raise ValueError("Candidate period confirmation flags are missing or invalid")
    eligible = pd.Series(False, index=rows.index)
    for _, flag, _ in TARGETS.values():
        if not rows[flag].isin([True, False]).all():
            raise ValueError(f"Expected explicit boolean eligibility: {flag}")
        eligible |= rows[flag].eq(True)
    confirmed = rows.target_period_confirmed.eq(True)
    if (eligible & ~confirmed).any():
        raise ValueError("Unconfirmed candidate was marked training eligible")
    if manifest["target_period_confirmed"] != bool(len(rows) and confirmed.all()):
        raise ValueError("Candidate/manifest period confirmation flags differ")
    selected = rows.loc[confirmed & eligible].copy()
    if selected.empty:
        raise ValueError("No confirmed eligible training cohort; unconfirmed candidates remain audit-only")
    require_confirmed_rows(selected)
    declaration = manifest["target_period_confirmation"]
    if not isinstance(declaration, dict) or evidence_digest(declaration) != manifest.get("target_period_evidence_sha256"):
        raise ValueError("Source period evidence declaration SHA256 differs")
    proofs = {}
    for cycle in declaration["cycles"]:
        proof = {key: value for key, value in declaration.items() if key != "cycles"}
        proof["cycle"] = cycle
        proofs[(cycle["facility_id"], cycle["cycle_id"])] = evidence_digest(proof)
    for row in selected.to_dict("records"):
        if proofs.get((row["facility_id"], row["cycle_id"])) != row["target_period_evidence_sha256"]:
            raise ValueError("Candidate/manifest period evidence mismatch")
    synthetic_ids = rows["facility_id"].astype(str).str.startswith("SYN_FARM_")
    if len(rows) and ((data_kind == "synthetic_schema_fixture" and not synthetic_ids.all())
                      or (data_kind != "synthetic_schema_fixture" and synthetic_ids.any())):
        raise ValueError("Synthetic facility identity and provenance disagree")
    selected_keys = set(zip(selected.facility_id, selected.cycle_id, strict=True))
    selected_declaration = {**declaration, "cycles": [cycle for cycle in declaration["cycles"]
                           if (cycle["facility_id"], cycle["cycle_id"]) in selected_keys]}
    cohort = {"candidate_rows": len(rows), "used_rows": len(selected),
              "unconfirmed_excluded_rows": int((~confirmed).sum()),
              "confirmed_ineligible_excluded_rows": int((confirmed & ~eligible).sum()),
              "source_all_periods_confirmed": manifest["target_period_confirmed"],
              "source_period_evidence_sha256": manifest["target_period_evidence_sha256"],
              "source_manifest_sha256": sha256(manifest_path), "candidate_sha256": sha256(path),
              "used_candidates": selected[["row_id", "facility_id", "cycle_id", "target_period_evidence_sha256"]].to_dict("records")}
    provenance = {"data_kind": data_kind, "target_assumption": manifest["target_assumption"],
                  "target_period_confirmed": True,
                  "target_period_evidence_sha256": evidence_digest(selected_declaration),
                  "target_period_confirmation": selected_declaration,
                  "training_cohort": cohort, "training_cohort_sha256": evidence_digest(cohort),
                  "source_manifest_sha256": sha256(manifest_path), "candidate_sha256": sha256(path),
                  "source_schema_sha256": manifest["schema_sha256"],
                  "interpretation": "SYNTHETIC RUNTIME DEMO ONLY" if data_kind == "synthetic_schema_fixture"
                  else "Document-backed period review; not independent provider verification"}
    require_model_confirmation(provenance)
    return selected, provenance, manifest


def regression_check(predictor, train_x, train_y, query_x):
    import torch
    altered = query_x.copy()
    for i, name in enumerate(FEATURES):
        altered[:, i] = 1_000_000 if name in NUMERIC else "__unseen_query__"
    snapshots = []
    for query in [query_x, altered]:
        inputs, standardized_y = predictor._prepare_reg_context(train_x, train_y, query)
        contexts = []
        for i, (values, categories) in enumerate(inputs):
            transformed, transformed_y, _ = predictor.get_xy_reg(
                values.copy(), i, standardized_y.copy(), predictor.preprocess_pipelines[i],
                categories.copy(), "Regression", unique_dataset_name="dsz_path_check")
            width = predictor.model.features_per_group
            padded = np.pad(transformed, ((0, 0), (0, (-transformed.shape[1]) % width)))
            tensor = torch.as_tensor(padded, dtype=torch.float32).reshape(1, len(padded), -1, width)
            with torch.inference_mode():
                internal = predictor.model.x_preprocess({"data": tensor, "eval_pos": len(train_x)})
            contexts.append((transformed[:len(train_x)].copy(), transformed_y.copy(),
                             internal["data"][:, :len(train_x)].numpy().copy()))
        snapshots.append(contexts)
    for normal, changed in zip(*snapshots, strict=True):
        np.testing.assert_allclose(normal[0], changed[0], atol=1e-12, rtol=1e-12, equal_nan=True)
        np.testing.assert_array_equal(normal[1], changed[1])
        np.testing.assert_allclose(normal[2], changed[2], atol=1e-6, rtol=1e-6, equal_nan=True)
    return {"pipelines_checked": len(snapshots[0]), "training_transforms_query_invariant": True,
            "internal_normalization_query_invariant": True, "heldout_labels_passed": False}


def run_limix_worker(data_dir, output_dir):
    # These optional modules/weights are deliberately absent from the CPU bundle.
    helper = ROOT / "scripts/train_adp_timing.py"
    if not helper.exists():
        raise RuntimeError("Optional pinned LimiX runtime is not included in the CPU bundle; omit --include-limix")
    from scripts.train_adp_timing import load_limix
    candidates, provenance, _ = read_data(data_dir)
    predictor, metadata = load_limix()  # Validates CUDA, pinned local weights/code; never downloads.
    result = {**provenance, "status": "running", "model": metadata, "targets": {}}
    for target, (label, _, unit) in TARGETS.items():
        rows = prepare_target(candidates, target)
        if rows["facility_id"].nunique() < 2:
            result["targets"][target] = {"status": "skipped_insufficient_data", "unit": unit,
                                         "reason": "Fewer than two facilities with eligible target records"}
            continue
        x = features(rows).to_numpy(object)
        predicted = np.full(len(rows), np.nan)
        checks, assignments = [], np.full(len(rows), -1)
        for number, (train, query) in enumerate(grouped_folds(rows)):
            print(f"LimiX {target} fold={number} data_kind={provenance['data_kind']}", flush=True)
            checks.append({"fold": number, **regression_check(predictor, x[train], rows.iloc[train][label].to_numpy(float), x[query])})
            predicted[query] = np.maximum(np.asarray(predictor.predict(
                x[train], rows.iloc[train][label].to_numpy(float), x[query], task_type="Regression",
                unique_dataset_name=f"dsz_{target}_{number}"), dtype=float).reshape(-1), 0)
            assignments[query] = number
        oof = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption", label]].copy()
        oof["fold"], oof["limix_2_400m"] = assignments, predicted
        oof["source_manifest_sha256"] = provenance["source_manifest_sha256"]
        path = output_dir / f"dsz_{target}_limix_oof.csv"
        oof.to_csv(path, index=False, encoding="utf-8-sig")
        result["targets"][target] = {"status": "completed", "unit": unit, **scores(rows[label], predicted), "checks": checks,
            "by_fold": {str(fold): scores(group[label], group["limix_2_400m"]) for fold, group in oof.groupby("fold")},
            "oof_file": path.name, "oof_sha256": sha256(path)}
    result["status"] = "completed"
    result["selection"] = "Optional frozen LimiX comparison only; CPU deployment selection is unchanged"
    write_json(output_dir / "dsz_limix_comparison.json", result)


def train(data_dir, output_dir, include_limix=False, limix_python=None):
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "dsz_model_metrics.json"
    try:
        candidates, provenance, manifest = read_data(data_dir)
    except Exception as error:
        write_json(metrics_path, {"status": "failed", "data_kind": "unverified_input",
                                  "failure": {"type": type(error).__name__, "message": str(error)}})
        raise
    result = {**provenance, "status": "running", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "features": FEATURES, "target_units": manifest["target_units"], "targets": {},
              "source_sha256": {name: sha256(ROOT / name) for name in
                                ["src/dsz_model.py", "src/dsz_period.py", "scripts/train_dsz.py", "scripts/predict_dsz.py"]},
              "limitations": ["Synthetic results are execution tests, never real farm accuracy.",
                              "Target periods require document-backed review; this is not independent provider verification.",
                              "Same facility cycles stay together; future-year and causal performance are not established.",
                              "CPU model selection uses the same OOF data; no untouched final test.",
                              "Revenue is gross receipts, not profit. No annualization or investment payback is inferred."]}
    write_json(metrics_path, result)
    try:
        for target in TARGETS:
            print(f"Training {target}: {provenance['data_kind']}", flush=True)
            rows = prepare_target(candidates, target)
            facility_count = int(rows["facility_id"].nunique())
            if facility_count < 2:
                result["targets"][target] = {"status": "skipped_insufficient_data", "rows": len(rows),
                    "facilities": facility_count, "target_column": TARGETS[target][0], "unit": TARGETS[target][2],
                    "reason": "Fewer than two independent facilities with eligible target records"}
                write_json(metrics_path, result)
                continue
            bundle, oof, summary = fit_target(rows, target, provenance)
            bundle_path = output_dir / f"dsz_{target}.joblib"
            oof_path = output_dir / f"dsz_{target}_oof.csv"
            joblib.dump(bundle, bundle_path)
            oof.to_csv(oof_path, index=False, encoding="utf-8-sig")
            summary.update(artifact_file=bundle_path.name, artifact_sha256=sha256(bundle_path),
                           oof_file=oof_path.name, oof_sha256=sha256(oof_path))
            result["targets"][target] = summary
            write_json(metrics_path, result)
        if not any(record["status"] == "completed" for record in result["targets"].values()):
            raise ValueError("Neither target has enough eligible independent facilities")
        if include_limix:
            python = Path(limix_python) if limix_python else ROOT / ".venv-limix/Scripts/python.exe"
            if not python.is_file():
                raise RuntimeError("LimiX Python runtime unavailable; supply --limix-python or omit --include-limix")
            subprocess.run([str(python), "-X", "utf8", str(Path(__file__).resolve()),
                            "--data-dir", str(data_dir.resolve()), "--output-dir", str(output_dir.resolve()),
                            "--limix-worker"], check=True)
            path = output_dir / "dsz_limix_comparison.json"
            extra = json.loads(path.read_text(encoding="utf-8"))
            if extra["candidate_sha256"] != provenance["candidate_sha256"] or extra["data_kind"] != provenance["data_kind"]:
                raise ValueError("Optional LimiX results use different data")
            result["optional_limix"] = {"file": path.name, "sha256": sha256(path), "status": extra["status"]}
        result["status"] = "completed"
        result["seconds"] = time.perf_counter() - started
        write_json(metrics_path, result)
        lines = ["# DSZ offline model execution", "", f"**{provenance['interpretation']}**", "",
                 f"data_kind: {provenance['data_kind']}", f"target_assumption: {provenance['target_assumption']}", "",
                 "OOF scores select a CPU model; they are not an independent final test.", "",
                 "| Target | Unit | Rows | Method | MAE | RMSE |", "|---|---|---:|---|---:|---:|"]
        for target, record in result["targets"].items():
            if record["status"] != "completed":
                lines.append(f"| {target} | {record['unit']} | {record['rows']} | skipped_insufficient_data | — | — |")
            for name, score in record.get("models", {}).items():
                lines.append(f"| {target} | {record['unit']} | {record['rows']} | {name} | {score['mae']:.4f} | {score['rmse']:.4f} |")
            if record.get("constant_training_fallbacks"):
                lines.append("\nAudited constant-training median fallbacks: " + json.dumps(record["constant_training_fallbacks"]))
        lines += ["", *result["limitations"]]
        (output_dir / "dsz_training_report.md").write_text("\n".join(lines), encoding="utf-8")
        return result
    except Exception as error:
        result.update(status="failed", failure={"type": type(error).__name__, "message": str(error)})
        write_json(metrics_path, result)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-limix", action="store_true", help="Opt into local approved CUDA comparison; no downloads")
    parser.add_argument("--limix-python", type=Path)
    parser.add_argument("--limix-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.limix_worker:
        run_limix_worker(args.data_dir, args.output_dir)
    else:
        summary = train(args.data_dir, args.output_dir, args.include_limix, args.limix_python)
        print(json.dumps({"status": summary["status"], "data_kind": summary["data_kind"],
                          "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))

'''[1:-1], "\n", False, "08872a97eced8100466c720596ef69f270c1f0e848ca5f75a8f16205b2526890")

# ===== SOURCE FILE: src/dsz_data.py =====
_save_source("src/dsz_data.py", r'''
"""Prepare the supplied DSZ schema; fixture data never represents real outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from src.dsz_period import candidate_proof, evidence_digest, evidence_json, load_confirmation

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config/dsz_schema.json"
FEATURES = ["crop", "region", "greenhouse_type", "greenhouse_size", "area_m2",
            "planned_start_year", "planned_start_month"]
TARGETS = {"reported_shipment_kg": "ALL_SHPMNT_KGUNT_QTY",
           "reported_revenue_krw": "ALL_INCM_AMT"}
TARGET_ASSUMPTION = "single_record_per_cycle"
MANAGEMENT_POLICIES = [TARGET_ASSUMPTION, "incremental_sum", "latest_cumulative"]
CANDIDATE_COLUMNS = ["row_id", "facility_id", "cycle_id"] + FEATURES + list(TARGETS) + [
    "shipment_eligible", "revenue_eligible", "shipment_numeric_valid", "revenue_numeric_valid",
    "data_kind", "target_assumption", "target_period_confirmed", "target_period_evidence_json",
    "target_period_evidence_sha256", "facility_source_file", "facility_source_row",
    "management_source_file", "management_source_row", "facility_raw_json",
    "management_raw_json"]
ISSUE_COLUMNS = ["dataset", "source_file", "source_row", "column", "reason"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    schema = json.loads(path.read_text(encoding="utf-8"))
    dictionary_path = ROOT / schema["dictionary_path"]
    if not dictionary_path.is_file() or sha256(dictionary_path) != schema["dictionary_sha256"]:
        raise ValueError("Source dictionary is missing or its SHA256 differs from the schema declaration")
    return schema


def parse_date(value: str, *, compact: bool = False) -> datetime | None:
    """VARCHAR2(8) dates are exactly YYYYMMDD; Oracle DATE accepts explicit exports."""
    formats = ["%Y%m%d"] if compact else ["%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S",
                                               "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S"]
    if compact and not re.fullmatch(r"\d{8}", value):
        return None
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def type_error(value: str, column: dict) -> str | None:
    if not value:
        return "missing_primary_key" if column["key"].startswith("PK") else None
    kind = column["type"]
    if kind.startswith("NUMBER"):
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?", value):
            return "invalid_number"
        try:
            number = Decimal(value)
        except InvalidOperation:
            return "invalid_number"
        if not number.is_finite():
            return "nonfinite_number"
        precision, _, scale = kind.removeprefix("NUMBER(").removesuffix(")").partition(",")
        _, raw_digits, exponent = number.as_tuple()
        digits = list(raw_digits)
        while len(digits) > 1 and digits[-1] == 0:
            digits.pop()
            exponent += 1
        decimals = max(-exponent, 0) if number else 0
        integer_digits = max(len(digits) + exponent, 0) if number else 0
        if decimals > int(scale or 0) or integer_digits > int(precision) - int(scale or 0):
            return "number_precision_or_scale"
    elif kind.startswith("VARCHAR"):
        length = int(re.search(r"\((\d+)\)", kind).group(1))
        if len(value) > length:
            return "text_length"
        if column["name"].endswith("_YMD") and parse_date(value, compact=True) is None:
            return "invalid_date"
    elif kind.startswith("DATE") and parse_date(value) is None:
        return "invalid_date"
    return None


def _csv_format(path: Path, table: dict, encoding: str) -> tuple[str, int, str]:
    """Use declared export format, or select an alias separator by exact headers."""
    official = path.name.casefold() == table.get("export_filename", "").casefold()
    if official:
        encoding = table.get("export_encoding", "utf-8")
        if encoding.lower().replace("-", "") == "utf8":
            encoding = "utf-8-sig"
        formats = [(table["export_delimiter"],
                    csv.QUOTE_MINIMAL if table["export_quoting"] else csv.QUOTE_NONE)]
    else:
        # Existing comma fixtures are quoted CSV; pipe exports are unquoted.
        formats = [(",", csv.QUOTE_MINIMAL), ("|", csv.QUOTE_NONE)]
    expected = {column["name"] for column in table["columns"]}
    matches = []
    for delimiter, quoting in formats:
        with path.open(encoding=encoding, newline="") as stream:
            try:
                header = next(csv.reader(stream, delimiter=delimiter, quoting=quoting), [])
            except csv.Error:
                continue
        if (len(header) == len(set(header)) and expected.issubset(header)
                and not {"_source_file", "_source_row"}.intersection(header)):
            matches.append((delimiter, quoting))
    if len(matches) != 1:
        raise ValueError(f"{path.name}: missing exact named columns, duplicate/reserved headers, "
                         "or ambiguous CSV delimiter; use the declared export headers and format")
    delimiter, quoting = matches[0]
    return delimiter, quoting, encoding


def load_tables(input_dir: Path, schema: dict, encoding: str = "utf-8-sig") -> tuple[dict, list]:
    """Select exact supplied table names or DZ_00N aliases, without column guessing."""
    aliases = {alias.upper(): table_id for table_id, table in schema["tables"].items()
               for alias in [table_id, table["filename"],
                             *table.get("filename_aliases", []),
                             *([Path(table["export_filename"]).stem] if table.get("export_filename") else [])]}
    paths = {}
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}:
            table_id = aliases.get(path.stem.upper())
            if table_id:
                if table_id in paths:
                    raise ValueError(f"More than one file for {table_id}: {paths[table_id].name}, {path.name}")
                paths[table_id] = path
    missing = [key for key, table in schema["tables"].items() if table["required"] and key not in paths]
    if missing:
        raise ValueError(f"Missing required dataset files: {missing}")
    tables, sources = {}, []
    for table_id, path in paths.items():
        csv_format = {}
        if path.suffix.lower() == ".csv":
            delimiter, quoting, file_encoding = _csv_format(path, schema["tables"][table_id], encoding)
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=file_encoding,
                                sep=delimiter, quoting=quoting)
            if not isinstance(frame.index, pd.RangeIndex):
                raise ValueError(f"{path.name}: CSV row contains more fields than the header")
            csv_format = {"delimiter": delimiter, "quoting": quoting != csv.QUOTE_NONE}
        else:
            with pd.ExcelFile(path) as workbook:
                if len(workbook.sheet_names) != 1:
                    raise ValueError(f"Expected one worksheet in {path.name}; export each dataset separately")
                frame = pd.read_excel(workbook, dtype=str, keep_default_na=False)
        frame = frame.fillna("").astype(str)
        expected = [col["name"] for col in schema["tables"][table_id]["columns"]]
        if missing_cols := set(expected) - set(frame.columns):
            raise ValueError(f"{table_id} missing exact named columns: {sorted(missing_cols)}")
        frame["_source_file"] = path.name
        frame["_source_row"] = range(2, len(frame) + 2)
        tables[table_id] = frame
        sources.append({"dataset": table_id, "file": path.name, "sha256": sha256(path),
                        "rows": len(frame), "encoding": file_encoding if path.suffix.lower() == ".csv" else "xlsx",
                        **csv_format,
                        "extra_columns": sorted(set(frame.columns) - set(expected) - {"_source_file", "_source_row"})})
    return tables, sources


def validate_table(table_id: str, frame: pd.DataFrame, table: dict) -> tuple[pd.DataFrame, list]:
    """Retain original text and mark bad cells/keys; never repair or merge source rows."""
    frame = frame.copy()
    issues, invalid = [], {index: set() for index in frame.index}
    for index, row in frame.iterrows():
        for column in table["columns"]:
            if reason := type_error(row[column["name"]], column):
                invalid[index].add(column["name"])
                issues.append({"dataset": table_id, "source_file": row["_source_file"],
                               "source_row": row["_source_row"], "column": column["name"], "reason": reason})
    keys = [column["name"] for column in table["columns"] if column["key"].startswith("PK")]
    canonical_keys = frame[keys].copy()
    for column in table["columns"]:
        key = column["name"]
        if key not in keys:
            continue
        if column["type"].startswith("NUMBER"):
            canonical_keys[key] = [str(Decimal(value).normalize()) if value and key not in invalid[index] else value
                                   for index, value in frame[key].items()]
        elif column["type"].startswith("DATE"):
            canonical_keys[key] = [parse_date(value).isoformat() if value and key not in invalid[index] else value
                                   for index, value in frame[key].items()]
    frame["_duplicate_key"] = canonical_keys.duplicated(keys, keep=False)
    raw_columns = [column["name"] for column in table["columns"]]
    for _, key_group in canonical_keys.loc[frame["_duplicate_key"]].groupby(keys, dropna=False):
        group = frame.loc[key_group.index]
        reason = "exact_duplicate_primary_key" if len(group[raw_columns].drop_duplicates()) == 1 else "conflicting_primary_key"
        for index, row in group.iterrows():
            invalid[index].update(keys)
            issues.append({"dataset": table_id, "source_file": row["_source_file"],
                           "source_row": row["_source_row"], "column": "+".join(keys), "reason": reason})
    frame["_invalid_columns"] = [invalid[index] for index in frame.index]
    frame["_raw_json"] = [json.dumps({key: row[key] for key in raw_columns}, ensure_ascii=False)
                           for _, row in frame.iterrows()]
    return frame, issues


def detect_data_kind(tables: dict, input_dir: Path) -> str:
    ids = pd.concat([tables[key]["FCLT_ID"] for key in ("DZ_002", "DZ_004")])
    nonempty = ids.loc[ids.ne("")]
    synthetic = nonempty.str.startswith("SYN_FARM_")
    marker = input_dir / "fixture_manifest.json"
    marked = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("data_kind") == "synthetic_schema_fixture"
    if synthetic.any() and not synthetic.all():
        raise ValueError("Synthetic and non-synthetic facility IDs must not be mixed")
    return "synthetic_schema_fixture" if marked or (not nonempty.empty and synthetic.all()) else "onsite_private_unverified"


def build_candidates(tables: dict, data_kind: str, policy: str = TARGET_ASSUMPTION,
                     confirmation: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if policy not in MANAGEMENT_POLICIES:
        raise ValueError(f"Unknown management policy: {policy}")
    facilities, management = tables["DZ_002"], tables["DZ_004"]
    exclusions, cycles = [], []
    declared_rows = {record["source_row"]: cycle for cycle in (confirmation or {}).get("cycles", [])
                     for record in cycle["records"]}

    def exclude(dataset, row, reason):
        exclusions.append({"dataset": dataset, "source_file": row["_source_file"],
                           "source_row": row["_source_row"], "column": "", "reason": reason})

    for _, row in facilities.iterrows():
        start = parse_date(row["FRMTM_BGNG_YMD"], compact=True)
        end = parse_date(row["FRMTM_END_YMD"], compact=True)
        if row["_invalid_columns"]:
            exclude("DZ_002", row, "invalid_schema_or_duplicate_key")
            continue
        if not row["FCLT_ID"] or not row["ITEM_NM"]:
            exclude("DZ_002", row, "missing_facility_or_crop")
            continue
        if start is None or end is None or end < start:
            exclude("DZ_002", row, "invalid_cycle_interval")
            continue
        if row["FRMTM_YR"] != str(start.year):
            exclude("DZ_002", row, "cycle_year_disagrees_with_start")
            continue
        if not row["HTHS_SFC"] or Decimal(row["HTHS_SFC"]) <= 0:
            exclude("DZ_002", row, "missing_or_nonpositive_area_m2")
            continue
        cycles.append({"raw": row, "start": start, "end": end, "surveys": [], "invalid_survey": False})
    # Keep invalid facility intervals in the join ambiguity check too: a rejected
    # duplicate cycle must not make an overlapping retained cycle appear unique.
    for _, row in management.iterrows():
        survey_date = parse_date(row["EXMN_YMD"], compact=True)
        if not row["FCLT_ID"] or survey_date is None:
            exclude("DZ_004", row, "missing_facility_or_survey_date")
            for cycle in cycles:
                if cycle["raw"]["FCLT_ID"] == row["FCLT_ID"]:
                    cycle["invalid_survey"] = True
            continue
        declared = declared_rows.get(int(row["_source_row"]))
        if declared:
            if declared["facility_id"] != row["FCLT_ID"]:
                raise ValueError("Declared management source row belongs to a different facility")
            # Survey date is a recording date, not necessarily the period end.
            # Only documented row-to-cycle identity can place a later survey.
            all_matches = facilities.loc[facilities["FCLT_ID"].eq(row["FCLT_ID"])
                                         & facilities["FRMTM_SNO"].eq(declared["cycle_id"]), "_source_row"].tolist()
            matches = [cycle for cycle in cycles if cycle["raw"]["FCLT_ID"] == row["FCLT_ID"]
                       and cycle["raw"]["FRMTM_SNO"] == declared["cycle_id"]]
        else:
            all_matches = []
            for _, facility in facilities.loc[facilities["FCLT_ID"].eq(row["FCLT_ID"])].iterrows():
                start = parse_date(facility["FRMTM_BGNG_YMD"], compact=True)
                end = parse_date(facility["FRMTM_END_YMD"], compact=True)
                if start and end and start <= survey_date <= end:
                    all_matches.append(facility["_source_row"])
            matches = [cycle for cycle in cycles if cycle["raw"]["FCLT_ID"] == row["FCLT_ID"]
                       and cycle["start"] <= survey_date <= cycle["end"]]
        if len(all_matches) != 1 or len(matches) != 1:
            exclude("DZ_004", row, "ambiguous_cycle_match" if len(all_matches) > 1 else "unmatched_eligible_cycle")
            for cycle in matches:
                cycle["invalid_survey"] = True
            continue
        if row["_invalid_columns"] - set(TARGETS.values()):
            exclude("DZ_004", row, "invalid_schema_or_duplicate_key")
            matches[0]["invalid_survey"] = True
            continue
        matches[0]["surveys"].append(row)
    candidates = []
    for cycle in cycles:
        row, surveys = cycle["raw"], cycle["surveys"]
        all_surveys = surveys
        reason = ""
        if cycle["invalid_survey"]:
            reason = "cycle_contains_invalid_survey"
        elif not surveys:
            reason = "no_unique_valid_survey"
        elif policy == "single_record_per_cycle" and len(surveys) > 1:
            reason = "multiple_surveys_no_aggregation"
        elif policy == "latest_cumulative":
            latest = max(survey["EXMN_YMD"] for survey in surveys)
            if sum(survey["EXMN_YMD"] == latest for survey in surveys) != 1:
                reason = "ambiguous_latest_survey_date"
            else:
                surveys = [survey for survey in surveys if survey["EXMN_YMD"] == latest]
        if reason:
            exclude("DZ_002", row, reason)
            for survey in surveys:
                exclude("DZ_004", survey, reason)
            continue
        proof = candidate_proof(confirmation, row, all_surveys, policy, data_kind)
        survey = surveys[0]
        source_rows = [int(survey["_source_row"]) for survey in surveys]
        candidate = {"row_id": f"DZ002:{row['_source_row']}:DZ004:" + ",".join(map(str, source_rows)),
                     "facility_id": row["FCLT_ID"], "cycle_id": row["FRMTM_SNO"],
                     "crop": row["ITEM_NM"], "region": row["AREA_NM"],
                     "greenhouse_type": row["SACT_INTLCK_SPR_NM"], "greenhouse_size": row["HTHS_SCL_CN"],
                     "area_m2": float(Decimal(row["HTHS_SFC"])),
                     "planned_start_year": cycle["start"].year, "planned_start_month": cycle["start"].month,
                     "data_kind": data_kind, "target_assumption": policy,
                     "target_period_confirmed": proof is not None,
                     "target_period_evidence_json": evidence_json(proof) if proof else "",
                     "target_period_evidence_sha256": evidence_digest(proof) if proof else "",
                     "facility_source_file": row["_source_file"], "facility_source_row": row["_source_row"],
                     "management_source_file": survey["_source_file"], "management_source_row": ",".join(map(str, source_rows)),
                     "facility_raw_json": row["_raw_json"], "management_raw_json": json.dumps(
                         [json.loads(survey["_raw_json"]) for survey in surveys], ensure_ascii=False)}
        for target, source in TARGETS.items():
            prefix = "shipment" if target == "reported_shipment_kg" else "revenue"
            valid = all(bool(survey[source]) and source not in survey["_invalid_columns"]
                        and Decimal(survey[source]) >= 0 for survey in surveys)
            value = float(sum(Decimal(survey[source]) for survey in surveys)) if valid else None
            candidate[target] = value
            candidate[f"{prefix}_numeric_valid"] = value is not None and value >= 0
            candidate[f"{prefix}_eligible"] = candidate[f"{prefix}_numeric_valid"] and proof is not None
            if not candidate[f"{prefix}_numeric_valid"]:
                exclude("DZ_004", survey, f"{target}_missing_invalid_or_negative")
        if proof is None:
            exclude("DZ_002", row, "target_period_unconfirmed_audit_only")
        candidates.append(candidate)
    return pd.DataFrame(candidates, columns=CANDIDATE_COLUMNS), pd.DataFrame(exclusions, columns=ISSUE_COLUMNS)


def prepare(input_dir: Path, output_dir: Path, *, encoding: str = "utf-8-sig",
            schema_path: Path = SCHEMA_PATH, management_policy: str = TARGET_ASSUMPTION,
            period_confirmation: Path | None = None) -> dict:
    if management_policy not in MANAGEMENT_POLICIES:
        raise ValueError(f"Unknown management policy: {management_policy}")
    schema = load_schema(schema_path)
    tables, sources = load_tables(input_dir, schema, encoding)
    data_kind = detect_data_kind(tables, input_dir)
    confirmation = load_confirmation(period_confirmation, sources, policy=management_policy, data_kind=data_kind)
    validation, inventory = [], {key: {"present": False, "rows": 0} for key in schema["tables"]}
    for table_id in tables:
        tables[table_id], issues = validate_table(table_id, tables[table_id], schema["tables"][table_id])
        validation.extend(issues)
        inventory[table_id] = {"present": True, "rows": len(tables[table_id]), "schema_valid_rows": int(
            tables[table_id]["_invalid_columns"].map(lambda columns: not columns).sum()),
            "model_usage": "pre_adoption_metadata" if table_id == "DZ_002" else
            "assumed_reported_targets" if table_id == "DZ_004" else "inventory_only_never_model_features"}
    candidates, exclusions = build_candidates(tables, data_kind, management_policy, confirmation)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {"candidates": output_dir / "dsz_model_candidates.csv",
             "exclusions": output_dir / "dsz_exclusions.csv", "validation": output_dir / "dsz_validation.csv"}
    candidates.to_csv(paths["candidates"], index=False, encoding="utf-8-sig")
    exclusions.to_csv(paths["exclusions"], index=False, encoding="utf-8-sig")
    pd.DataFrame(validation, columns=ISSUE_COLUMNS).to_csv(paths["validation"], index=False, encoding="utf-8-sig")
    manifest = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_kind": data_kind, "input_dir": str(input_dir.resolve()),
                "schema_sha256": sha256(schema_path), "source_dictionary_sha256": schema["dictionary_sha256"],
                "target_assumption": management_policy,
                "target_period_confirmed": bool(len(candidates) and candidates.target_period_confirmed.all()),
                "target_period_evidence_sha256": evidence_digest(confirmation) if confirmation else None,
                "target_period_confirmation": confirmation,
                "period_confirmation_level": "documented_reviewer_declaration_not_independent_provider_verification",
                "target_interpretation": {
                    "single_record_per_cycle": "Exactly one survey in a uniquely matched facility cycle, assumed cycle-total candidate; period not proven by dictionary.",
                    "incremental_sum": "Operator assumes distinct survey records are nonoverlapping increments; sum complete nonnegative targets, with no partial sums.",
                    "latest_cumulative": "Operator assumes survey records are cumulative; take the unique latest survey date within the uniquely matched cycle."
                }[management_policy],
                "target_units": {"reported_shipment_kg": "kg", "reported_revenue_krw": "KRW_gross_revenue_not_profit"},
                "area_unit": "m2_from_HTHS_SFC", "features": FEATURES, "group_column": "facility_id",
                "sources": sources, "inventory": inventory, "candidate_rows": len(candidates),
                "target_eligible_rows": {target: int(candidates[f'{prefix}_eligible'].sum()) for target, prefix in
                                         [("reported_shipment_kg", "shipment"), ("reported_revenue_krw", "revenue")]},
                "validation_issue_counts": dict(Counter(item["reason"] for item in validation)),
                "exclusion_reason_counts": exclusions["reason"].value_counts().to_dict(),
                "artifacts": {key: {"file": path.name, "sha256": sha256(path)} for key, path in paths.items()},
                "limitations": ["No post-planting environment/growth/weather records are model inputs.",
                                "Unconfirmed management periods are audit-only; numeric validity does not authorize training.",
                                "Period evidence records a document-backed review, not independent provider verification.",
                                "Start year/month represent the planned start available at prediction time.",
                                "Synthetic fixtures demonstrate execution only, never real predictive accuracy.",
                                "Private input data and predictions must stay within the approved safe-zone workflow."]}
    (output_dir / "dsz_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

'''[1:-1], "\n", False, "c9177f7d3defb21a6e9e0daff18f2fe01ffd5cc2ea70687b89020fb939547ec5")

# ===== SOURCE FILE: src/dsz_inseason.py =====
_save_source("src/dsz_inseason.py", r'''
"""Offline cycle-total shipment updates with documented labels and cutoff-safe inputs."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from scripts.train_dsz import read_data
from src.dsz_data import ISSUE_COLUMNS, parse_date
from src.dsz_model import CATEGORICAL, FEATURES, METHODS, NUMERIC, features, fit_cpu, grouped_folds, prepare_target, scores, sha256
from src.dsz_observations import OBSERVATION_NUMERIC, build_observation_features, load_observation_tables
from src.dsz_period import evidence_digest, require_confirmed_rows, require_model_confirmation

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ["row_id", "facility_id", "cycle_id"]
LABEL = "reported_shipment_kg"
SCOPE = "inseason_cycle_total"
SOURCE_FILES = ["src/dsz_inseason.py", "src/dsz_observations.py", "src/dsz_model.py",
                "src/dsz_period.py", "src/dsz_data.py", "scripts/train_dsz.py",
                "scripts/run_dsz_inseason.py", "config/dsz_schema.json"]
LIMITATIONS = [
    "Synthetic data demonstrate execution only, never actual farm predictive accuracy.",
    "Cycle labels require document-backed period review; this is not independent provider verification.",
    "Only same-facility, uniquely matched cycle observations at or before the fixed cutoff are used.",
    "Observation availability at the historical prediction time is not independently verified; this is retrospective evaluation.",
    "Facility-group OOF scores select a model and are not an untouched final test.",
    "Latest-year checks report fixed candidates separately, never an independent score of the full-data OOF winner.",
    "The target is whole-cycle shipment kg, not remaining shipment, profit, payback or equipment impact.",
    "Sensor row counts do not increase the number of independent training facilities or cycles.",
]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_hashes() -> dict:
    return {name: sha256(ROOT / name) for name in SOURCE_FILES}


def verify_raw_sources(sources: list[dict], manifest: dict) -> None:
    """A prepared label and observation summary must originate from the same export."""
    def identities(items):
        return sorted((item["dataset"], item["file"], item["sha256"]) for item in items)
    if identities(sources) != identities(manifest.get("sources", [])):
        raise ValueError("Raw source files/SHA differ from the preparation manifest; prepare again")


def model_features(rows: pd.DataFrame, extended: bool) -> pd.DataFrame:
    """Explicit whitelist: identities, outcomes, raw JSON and dates never enter X."""
    x = features(rows)
    if extended:
        if missing := set(OBSERVATION_NUMERIC) - set(rows.columns):
            raise ValueError(f"Missing observation feature columns: {sorted(missing)}")
        observations = rows[OBSERVATION_NUMERIC].apply(pd.to_numeric, errors="raise").astype(float)
        if np.isinf(observations.to_numpy()).any():
            raise ValueError("Observation features cannot contain infinity")
        x = pd.concat([x, observations], axis=1)
    return x


class TrainFoldModel:
    """Learn imputation statistics only from the current training fold."""

    def __init__(self, method: str, extended: bool):
        self.method = method
        self.extended = extended

    def fit(self, rows: pd.DataFrame, y):
        x = model_features(rows, self.extended)
        self.imputer = None
        if self.extended and self.method in {"catboost", "xgboost"}:
            numeric = NUMERIC + OBSERVATION_NUMERIC
            self.imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
            values = self.imputer.fit_transform(x[numeric])
            self.numeric_features = self.imputer.get_feature_names_out(numeric).tolist()
            x = pd.concat([x[CATEGORICAL], pd.DataFrame(values, index=x.index, columns=self.numeric_features)], axis=1)
            self.model, self.fallback = fit_cpu(self.method, x, y, numeric_features=self.numeric_features)
        else:
            # Both median comparators deliberately ignore observation features.
            self.model, self.fallback = fit_cpu(self.method, x[FEATURES], y)
        return self

    def predict(self, rows: pd.DataFrame):
        x = model_features(rows, self.extended)
        if self.imputer is not None:
            values = self.imputer.transform(x[NUMERIC + OBSERVATION_NUMERIC])
            x = pd.concat([x[CATEGORICAL], pd.DataFrame(values, index=x.index, columns=self.numeric_features)], axis=1)
        else:
            x = x[FEATURES]
        values = np.maximum(np.asarray(self.model.predict(x), dtype=float), 0)
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite shipment predictions")
        return values


def matched_provenance(provenance: dict, rows: pd.DataFrame) -> dict:
    """Narrow the period declaration to the actual matched modelling cohort."""
    keys = set(zip(rows.facility_id, rows.cycle_id, strict=True))
    declaration = {**provenance["target_period_confirmation"], "cycles": [cycle for cycle in
        provenance["target_period_confirmation"]["cycles"] if (cycle["facility_id"], cycle["cycle_id"]) in keys]}
    original = provenance["training_cohort"]
    removed = original["used_rows"] - len(rows)
    cohort = {**original, "used_rows": len(rows),
              "confirmed_ineligible_excluded_rows": original["confirmed_ineligible_excluded_rows"] + removed,
              "inseason_additional_excluded_rows": removed,
              "eligibility_definition": "confirmed shipment, selected crop, valid cutoff and linked observations",
              "used_candidates": rows[IDENTITY + ["target_period_evidence_sha256"]].to_dict("records")}
    result = {**provenance, "target_period_confirmation": declaration,
              "target_period_evidence_sha256": evidence_digest(declaration),
              "training_cohort": cohort, "training_cohort_sha256": evidence_digest(cohort)}
    require_model_confirmation(result)
    return result


def join_training_rows(candidates: pd.DataFrame, observation_rows: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    if observation_rows.duplicated(IDENTITY).any() or observation_rows.row_id.duplicated().any():
        raise ValueError("Observation builder returned duplicate request identities")
    candidate_keys = set(map(tuple, candidates[IDENTITY].to_numpy()))
    if not set(map(tuple, observation_rows[IDENTITY].to_numpy())).issubset(candidate_keys):
        raise ValueError("Observation builder returned a different facility/cycle")
    joined = candidates.merge(observation_rows, on=IDENTITY, how="inner", validate="one_to_one", suffixes=("", "_observation"))
    for name in FEATURES:
        left, right = joined[name], joined[f"{name}_observation"]
        same = np.isclose(pd.to_numeric(left), pd.to_numeric(right), rtol=0, atol=1e-9) if name in NUMERIC else left.eq(right)
        if not np.all(same):
            raise ValueError(f"Prepared/raw facility feature mismatch: {name}")
    if not joined.has_observations.isin([True, False]).all():
        raise ValueError("Observation presence must be explicitly boolean")
    missing = joined.loc[~joined.has_observations, IDENTITY].to_dict("records")
    for item in missing:
        item["reason"] = "no_usable_observation_before_cutoff"
    joined = joined.loc[joined.has_observations].drop(columns=[f"{name}_observation" for name in FEATURES])
    return joined.sort_values("row_id").reset_index(drop=True), missing


def compare_models(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    require_confirmed_rows(rows)
    folds = grouped_folds(rows)
    oof = rows[IDENTITY + ["as_of", LABEL]].copy()
    oof["fold"] = -1
    records, fallback_records = [], []
    for number, (training, query) in enumerate(folds):
        records.append({"fold": number, "train_row_ids": rows.iloc[training].row_id.tolist(),
                        "test_row_ids": rows.iloc[query].row_id.tolist(),
                        "train_facilities": int(rows.iloc[training].facility_id.nunique()),
                        "test_facilities": int(rows.iloc[query].facility_id.nunique()), "facility_overlap": False})
        oof.loc[query, "fold"] = number
        for mode in ["baseline", "extended"]:
            for method in METHODS:
                model = TrainFoldModel(method, extended=mode == "extended").fit(rows.iloc[training], rows.iloc[training][LABEL])
                oof.loc[query, f"{mode}__{method}"] = model.predict(rows.iloc[query])
                if model.fallback:
                    fallback_records.append({"fold": number, "mode": mode, "method": method, "reason": model.fallback})
    metrics = {mode: {method: {**scores(rows[LABEL], oof[f"{mode}__{method}"]),
                "by_fold": {str(number): scores(group[LABEL], group[f"{mode}__{method}"])
                            for number, group in oof.groupby("fold")}}
              for method in METHODS} for mode in ["baseline", "extended"]}
    selected = {mode: min(METHODS, key=lambda method: metrics[mode][method]["mae"]) for mode in metrics}
    return oof, {"models": metrics, "selected_methods": selected, "folds": records,
                 "same_rows_and_folds_for_all_candidates": True, "constant_training_fallbacks": fallback_records,
                 "selection": "lowest facility-group OOF MAE; model-selection evidence, not untouched final-test accuracy"}


def label_available_after(row: pd.Series) -> datetime | None:
    """Daily outcome dates are usable only after every selected survey day ends."""
    try:
        end_value = json.loads(row["target_period_evidence_json"])["cycle"]["end"]
        end = datetime.strptime(end_value, "%Y-%m-%d")
        surveys = json.loads(row["management_raw_json"])
        if not isinstance(surveys, list) or not surveys:
            return None
        dates = [end]
        for survey in surveys:
            value = survey.get("EXMN_YMD") if isinstance(survey, dict) else None
            observed = parse_date(value, compact=True) if isinstance(value, str) else None
            if observed is None:
                return None
            dates.append(observed)
        return max(dates) + timedelta(days=1)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def latest_year_check(rows: pd.DataFrame) -> dict:
    """Fixed candidate temporal checks; do not call the OOF winner independently tested."""
    years = sorted(rows.planned_start_year.unique())
    if len(years) < 2:
        return {"status": "skipped", "reason": "Only one start year in the matched cohort"}
    query = rows.loc[rows.planned_start_year.eq(years[-1])]
    cutoff = pd.to_datetime(query.as_of).min()
    earlier = rows.loc[rows.planned_start_year.lt(years[-1])]
    training_indices, exclusions = [], []
    query_facilities = set(query.facility_id)
    for index, row in earlier.iterrows():
        available = label_available_after(row)
        reason = None
        if row.facility_id in query_facilities:
            reason = "facility_present_in_test"
        elif available is None:
            reason = "missing_or_invalid_label_availability_date"
        elif available > cutoff:
            reason = "label_not_available_by_test_cutoff"
        if reason:
            exclusions.append({**{key: row.get(key, "") for key in IDENTITY}, "reason": reason,
                               "label_available_after": available.isoformat() if available else None})
        else:
            training_indices.append(index)
    training = rows.loc[training_indices]
    temporal_audit = {
        "first_test_cutoff": cutoff.isoformat(), "earlier_candidate_rows": len(earlier),
        "excluded_training_rows": len(exclusions), "training_exclusions": exclusions,
        "exclusion_counts": {name: int(count) for name, count in
                             pd.Series([item["reason"] for item in exclusions], dtype=str).value_counts().items()},
        "label_availability_rule": "max(cycle end + 1 day, every selected EXMN_YMD + 1 day) <= first test cutoff",
        "label_availability_limitation": "Survey dates bound retrospective label availability; actual publication/loading time is not independently verified",
    }
    if training.empty or training.facility_id.nunique() < 2:
        return {"status": "skipped", "reason": "Fewer than two earlier completed training facilities after excluding test facilities",
                "test_year": int(years[-1]), "train_rows": len(training), "test_rows": len(query), **temporal_audit}
    results = {}
    for mode in ["baseline", "extended"]:
        results[mode] = {}
        for method in METHODS:
            model = TrainFoldModel(method, mode == "extended").fit(training, training[LABEL])
            results[mode][method] = {**scores(query[LABEL], model.predict(query)), "fallback": model.fallback}
    return {"status": "completed", "test_year": int(years[-1]), **temporal_audit,
            "train_row_ids": training.row_id.tolist(), "test_row_ids": query.row_id.tolist(),
            "facility_overlap": False, "models": results,
            "interpretation": "Fixed-candidate retrospective future-year comparison; not a final test of the full-data OOF-selected model"}


def train_inseason(data_dir: Path, input_dir: Path, output_dir: Path, *, cutoff_days: int = 30,
                   window_days: int = 28, crop: str = "딸기", encoding: str = "utf-8-sig") -> dict:
    if output_dir.exists():
        raise FileExistsError("Output directory already exists; choose a new run directory")
    if cutoff_days < 1 or window_days < 1 or not crop.strip():
        raise ValueError("Positive cutoff/window days and a crop are required")
    output_dir.mkdir(parents=True)
    metrics_path = output_dir / "dsz_inseason_metrics.json"
    try:
        candidates, provenance, manifest = read_data(data_dir)
        if manifest["schema_sha256"] != sha256(ROOT / "config/dsz_schema.json"):
            raise ValueError("Preparation schema differs from the current observation schema")
        shipment = prepare_target(candidates, "shipment")
        scope_exclusions = [{**row, "reason": "shipment_ineligible" if not row["shipment_eligible"] else "outside_selected_crop"}
                            for row in candidates.loc[~candidates.shipment_eligible | ~candidates.crop.eq(crop),
                                IDENTITY + ["crop", "shipment_eligible"]].to_dict("records")]
        shipment = shipment.loc[shipment.crop.eq(crop)].reset_index(drop=True)
        if shipment.empty:
            raise ValueError("No confirmed eligible shipment rows for the selected crop")
        tables, sources, validation = load_observation_tables(input_dir, encoding=encoding)
        verify_raw_sources(sources, manifest)
        observation_rows, audit = build_observation_features(tables, shipment[IDENTITY], cutoff_days, window_days)
        rows, no_observation = join_training_rows(shipment, observation_rows)
        audit = {**audit, "no_observation_exclusions": no_observation,
                 "scope_exclusions": scope_exclusions,
                 "confirmed_shipment_rows": len(shipment), "matched_rows": len(rows),
                 "matched_facilities": int(rows.facility_id.nunique()), "raw_sources": sources}
        write_json(output_dir / "observation_audit.json", audit)
        pd.DataFrame(validation, columns=ISSUE_COLUMNS).to_csv(output_dir / "observation_validation.csv", index=False, encoding="utf-8-sig")
        if rows.facility_id.nunique() < 2:
            raise ValueError("At least two independent facilities with linked observations are required")
        provenance = matched_provenance(provenance, rows)
        model_features(rows, True)
        feature_manifest = {"baseline": FEATURES, "extended": FEATURES + OBSERVATION_NUMERIC,
                            "numeric_observation_features": OBSERVATION_NUMERIC,
                            "excluded_from_features": [*IDENTITY, LABEL, "reported_revenue_krw", "as_of", "cycle_end", "raw_json"],
                            "cutoff_days": cutoff_days, "window_days": window_days,
                            "as_of_definition": "cycle start + cutoff_days at 00:00 local naive source time",
                            "missing_values": "train-fold-only median and missing indicators; all-missing columns retained",
                            "prediction_scope": SCOPE, "target": "shipment", "unit": "kg", "crop": crop}
        cohort = rows[IDENTITY + ["as_of"]].to_dict("records")
        oof, comparison = compare_models(rows)
        selected = comparison["selected_methods"]["extended"]
        baseline_mae = comparison["models"]["baseline"][comparison["selected_methods"]["baseline"]]["mae"]
        extended_mae = comparison["models"]["extended"][selected]["mae"]
        comparison["observation_comparison"] = {
            "same_matched_cohort": True, "baseline_best_oof_mae_kg": baseline_mae,
            "extended_best_oof_mae_kg": extended_mae, "oof_mae_reduction_kg": baseline_mae - extended_mae,
            "interpretation": "Descriptive OOF comparison after model selection; not proof of real or causal improvement"}
        model = TrainFoldModel(selected, True).fit(rows, rows[LABEL])
        bundle = {**provenance, "features": FEATURES + OBSERVATION_NUMERIC,
                  "feature_manifest": feature_manifest, "feature_manifest_sha256": evidence_digest(feature_manifest),
                  "matched_cohort": cohort, "matched_cohort_sha256": evidence_digest({"rows": cohort}),
                  "selected_cpu_model": selected, "model": model, "model_fallback": model.fallback,
                  "training_crops": [crop], "target": "shipment", "unit": "kg", "prediction_scope": SCOPE,
                  "cutoff_days": cutoff_days, "window_days": window_days, "source_sha256": source_hashes(),
                  "raw_sources": sources, "limitations": LIMITATIONS}
        artifact = output_dir / "dsz_inseason_shipment.joblib"
        oof_path = output_dir / "dsz_inseason_oof.csv"
        features_path = output_dir / "dsz_inseason_training_rows.csv"
        joblib.dump(bundle, artifact)
        oof.to_csv(oof_path, index=False, encoding="utf-8-sig")
        rows[IDENTITY + ["as_of"] + FEATURES + OBSERVATION_NUMERIC + [LABEL]].to_csv(features_path, index=False, encoding="utf-8-sig")
        result = {key: value for key, value in bundle.items() if key != "model"}
        result.update(status="completed", **comparison, latest_year_check=latest_year_check(rows),
                      rows=len(rows), facilities=int(rows.facility_id.nunique()),
                      artifact_file=artifact.name, artifact_sha256=sha256(artifact),
                      oof_file=oof_path.name, oof_sha256=sha256(oof_path),
                      training_features_file=features_path.name, training_features_sha256=sha256(features_path),
                      observation_audit_file="observation_audit.json")
        write_json(metrics_path, result)
        return result
    except Exception as error:
        write_json(metrics_path, {"status": "failed", "data_kind": "unverified_input", "prediction_scope": SCOPE,
                                 "failure": {"type": type(error).__name__, "message": str(error)}})
        raise


def load_local_bundle(artifact_dir: Path) -> tuple[dict, dict]:
    """Load only self-generated trusted local joblib files, never untrusted uploads."""
    manifest = json.loads((artifact_dir / "dsz_inseason_metrics.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed" or manifest.get("prediction_scope") != SCOPE:
        raise ValueError("Completed in-season training artifacts are required")
    require_model_confirmation(manifest)
    if manifest.get("source_sha256") != source_hashes():
        raise ValueError("Current model/feature-builder source hashes differ from training")
    if manifest.get("features") != FEATURES + OBSERVATION_NUMERIC:
        raise ValueError("Artifact feature whitelist differs")
    if evidence_digest(manifest["feature_manifest"]) != manifest.get("feature_manifest_sha256"):
        raise ValueError("Feature manifest SHA differs")
    if evidence_digest({"rows": manifest["matched_cohort"]}) != manifest.get("matched_cohort_sha256"):
        raise ValueError("Matched cohort SHA differs")
    path = artifact_dir / manifest["artifact_file"]
    if path.resolve().parent != artifact_dir.resolve() or sha256(path) != manifest["artifact_sha256"]:
        raise ValueError("Local model artifact path/SHA differs")
    bundle = joblib.load(path)
    for key, value in bundle.items():
        if key != "model" and value != manifest.get(key):
            raise ValueError(f"Model/manifest provenance mismatch: {key}")
    require_model_confirmation(bundle)
    return bundle, manifest


def predict_inseason(artifact_dir: Path, input_dir: Path, requests: pd.DataFrame, *, encoding: str = "utf-8-sig") -> tuple[pd.DataFrame, dict]:
    if set(requests.columns) != {"plan_id", "facility_id", "cycle_id"} or requests.empty:
        raise ValueError("Requests must contain only plan_id, facility_id, cycle_id and at least one row")
    if requests.isna().any().any():
        raise ValueError("Request identities cannot be missing")
    requests = requests.astype(str).copy()
    if requests.apply(lambda column: column.str.strip().eq("")).any().any() or requests.plan_id.duplicated().any() or requests.duplicated(["facility_id", "cycle_id"]).any():
        raise ValueError("Request identities must be present and unique")
    bundle, manifest = load_local_bundle(artifact_dir)
    tables, sources, validation = load_observation_tables(input_dir, encoding=encoding)
    request_rows = requests.rename(columns={"plan_id": "row_id"})
    rows, audit = build_observation_features(tables, request_rows, bundle["cutoff_days"], bundle["window_days"])
    expected = set(map(tuple, request_rows[IDENTITY].to_numpy()))
    actual = set(map(tuple, rows[IDENTITY].to_numpy()))
    absent = rows.loc[~rows.has_observations, IDENTITY].to_dict("records")
    if expected != actual or absent:
        raise ValueError("Unmatched/invalid request or no observations; no silent baseline fallback: "
                         + json.dumps({"excluded_requests": audit.get("excluded_requests", []), "no_observations": absent}, ensure_ascii=False))
    if not set(rows.crop).issubset(bundle["training_crops"]):
        raise ValueError("Query crop is outside the trained crop scope")
    today = pd.Timestamp(datetime.now().date())
    if pd.to_datetime(rows.as_of).gt(today).any():
        raise ValueError("A requested prediction cutoff is in the future; observed inputs are not yet available")
    synthetic = rows.facility_id.str.startswith("SYN_FARM_")
    if (bundle["data_kind"] == "synthetic_schema_fixture" and not synthetic.all()) or (
            bundle["data_kind"] != "synthetic_schema_fixture" and synthetic.any()):
        raise ValueError("Synthetic and real facility identities cannot be mixed")
    result = rows[IDENTITY + ["as_of"]].rename(columns={"row_id": "plan_id"}).copy()
    result["prediction"] = bundle["model"].predict(rows)
    for name in ["target", "unit", "prediction_scope", "cutoff_days", "window_days", "data_kind", "target_assumption",
                 "target_period_confirmed", "target_period_evidence_sha256", "source_manifest_sha256", "candidate_sha256",
                 "training_cohort_sha256", "matched_cohort_sha256", "feature_manifest_sha256", "selected_cpu_model"]:
        result[name] = bundle[name]
    result["query_sources_sha256"] = evidence_digest({"sources": sources})
    result["training_artifact_sha256"] = manifest["artifact_sha256"]
    result["interpretation"] = "SYNTHETIC RUNTIME DEMO ONLY" if bundle["data_kind"] == "synthetic_schema_fixture" else "Whole-cycle shipment update; retrospective availability assumptions, not economic or causal validation"
    metadata = {"prediction_scope": SCOPE, "data_kind": bundle["data_kind"], "raw_sources": sources,
                "query_sources_sha256": evidence_digest({"sources": sources}), "observation_audit": audit,
                "validation_issues": validation, "source_sha256": bundle["source_sha256"],
                "training_manifest_sha256": sha256(artifact_dir / "dsz_inseason_metrics.json"),
                "training_artifact_sha256": manifest["artifact_sha256"], "feature_manifest": bundle["feature_manifest"],
                "limitations": LIMITATIONS}
    return result, metadata

'''[1:-1], "\n", False, "3d46d2487a9b14909d65bcc2dcd0c12ce5400d02cb0d7cc7f9157bc9f40133fe")

# ===== SOURCE FILE: src/dsz_model.py =====
_save_source("src/dsz_model.py", r'''
"""Offline recorded-cycle candidate models; synthetic results are runtime tests only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from src.dsz_period import require_confirmed_rows, require_model_confirmation

NUMERIC = ["area_m2", "planned_start_year", "planned_start_month"]
CATEGORICAL = ["crop", "region", "greenhouse_type", "greenhouse_size"]
FEATURES = CATEGORICAL + NUMERIC
TARGETS = {"shipment": ("reported_shipment_kg", "shipment_eligible", "kg"),
           "revenue": ("reported_revenue_krw", "revenue_eligible", "KRW")}
METHODS = ["crop_median", "area_scaled_crop_median", "catboost", "xgboost"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def features(rows: pd.DataFrame) -> pd.DataFrame:
    missing = set(FEATURES) - set(rows.columns)
    if missing:
        raise ValueError(f"Missing planned feature columns: {sorted(missing)}")
    result = rows[FEATURES].copy()
    for name in CATEGORICAL:
        result[name] = result[name].fillna("__missing__").astype(str).replace("", "__missing__")
    if result["crop"].isin(["", "__missing__"]).any():
        raise ValueError("crop must be specified")
    for name in NUMERIC:
        result[name] = pd.to_numeric(result[name], errors="raise")
        if not np.isfinite(result[name]).all():
            raise ValueError(f"Feature must be finite: {name}")
    if result["area_m2"].le(0).any():
        raise ValueError("area_m2 must be positive, in square metres")
    for name in ["planned_start_year", "planned_start_month"]:
        if result[name].mod(1).ne(0).any():
            raise ValueError(f"Feature must be an integer: {name}")
    if not result["planned_start_month"].between(1, 12).all():
        raise ValueError("planned_start_month must be 1..12")
    return result


def prepare_target(candidates: pd.DataFrame, target: str) -> pd.DataFrame:
    label, eligible, _ = TARGETS[target]
    required = FEATURES + [label, eligible, "row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]
    if missing := set(required) - set(candidates.columns):
        raise ValueError(f"Missing candidate columns: {sorted(missing)}")
    if not candidates[eligible].isin([True, False]).all():
        raise ValueError(f"Expected explicit boolean eligibility: {eligible}")
    rows = candidates.loc[candidates[eligible].eq(True)].copy()
    require_confirmed_rows(rows)
    if not candidates.get("target_period_confirmed", pd.Series(dtype=bool)).eq(True).any():
        raise ValueError("Unconfirmed target period; no confirmed training cohort")
    if rows["row_id"].duplicated().any() or rows.duplicated(["facility_id", "cycle_id"]).any():
        raise ValueError("Duplicate candidate identity")
    identity = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]]
    if identity.isna().any().any() or identity.eq("").any().any():
        raise ValueError("Missing identity or data provenance")
    rows[label] = pd.to_numeric(rows[label], errors="raise")
    if not np.isfinite(rows[label]).all() or rows[label].lt(0).any():
        raise ValueError("Eligible target must be finite and nonnegative; missing is not zero")
    features(rows)
    return rows.sort_values("row_id").reset_index(drop=True)


def grouped_folds(rows: pd.DataFrame):
    count = int(rows["facility_id"].nunique())
    if count < 2:
        raise ValueError("At least two independent facility IDs are required")
    folds = list(GroupKFold(n_splits=min(5, count)).split(rows, groups=rows["facility_id"]))
    seen = np.zeros(len(rows), dtype=int)
    for train, query in folds:
        if set(rows.iloc[train]["facility_id"]) & set(rows.iloc[query]["facility_id"]):
            raise ValueError("Facility overlap")
        seen[query] += 1
    if not np.all(seen == 1):
        raise ValueError("Every row needs exactly one held-out prediction")
    return folds


class CropMedian:
    """Training-only crop medians, optionally per square metre."""

    def __init__(self, area_scaled: bool = False):
        self.area_scaled = area_scaled

    def fit(self, x: pd.DataFrame, y):
        values = np.asarray(y, dtype=float)
        if self.area_scaled:
            values = values / x["area_m2"].to_numpy(float)
        rows = pd.DataFrame({"crop": x["crop"].to_numpy(), "value": values})
        self.medians = rows.groupby("crop")["value"].median().to_dict()
        self.global_median = float(np.median(values))
        return self

    def predict(self, x: pd.DataFrame):
        values = x["crop"].map(self.medians).fillna(self.global_median).to_numpy(float)
        return values * x["area_m2"].to_numpy(float) if self.area_scaled else values


def make_model(name: str, *, numeric_features: list[str] | None = None):
    numeric = NUMERIC if numeric_features is None else numeric_features
    if name in METHODS[:2]:
        return CropMedian(area_scaled=name == "area_scaled_crop_median")
    if name == "catboost":
        from catboost import CatBoostRegressor
        return CatBoostRegressor(iterations=180, depth=4, learning_rate=0.05, loss_function="MAE",
                                 l2_leaf_reg=5, random_seed=42, thread_count=2,
                                 cat_features=CATEGORICAL, allow_writing_files=False, verbose=False)
    if name == "xgboost":
        from sklearn.compose import ColumnTransformer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        from xgboost import XGBRegressor
        return Pipeline([
            ("encode", ColumnTransformer([
                ("category", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
                ("numeric", "passthrough", numeric)])),
            ("model", XGBRegressor(n_estimators=180, max_depth=3, learning_rate=0.05,
                                   objective="reg:absoluteerror", reg_lambda=5,
                                   subsample=0.9, random_state=42, n_jobs=2))])
    raise ValueError(f"Unknown CPU method: {name}")


def scores(actual, predicted) -> dict:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if not len(actual) or len(actual) != len(predicted) or not np.isfinite(predicted).all():
        raise ValueError("Missing/nonfinite predictions")
    error = predicted - actual
    return {"n_scored": len(actual), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean()))}


def fit_cpu(name, x, y, *, numeric_features: list[str] | None = None):
    """Audit degenerate ML folds instead of failing on valid zero/constant labels."""
    reason = None
    if name in {"catboost", "xgboost"}:
        if pd.Series(np.asarray(y)).nunique() == 1:
            reason = "constant_training_target"
        elif x.nunique(dropna=False).le(1).all():
            reason = "constant_training_features"
    model = CropMedian() if reason else (
        make_model(name) if numeric_features is None else make_model(name, numeric_features=numeric_features))
    return model.fit(x, y), reason


def fit_target(rows: pd.DataFrame, target: str, provenance: dict):
    require_confirmed_rows(rows)
    require_model_confirmation(provenance)
    label, _, unit = TARGETS[target]
    folds = grouped_folds(rows)
    x = features(rows)
    oof = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption", label]].copy()
    oof["fold"] = -1
    oof["crop_seen_in_training"] = False
    oof["source_manifest_sha256"] = provenance["source_manifest_sha256"]
    for name in METHODS:
        oof[name] = np.nan
    records, fallbacks = [], []
    for number, (train, query) in enumerate(folds):
        for name in METHODS:
            model, reason = fit_cpu(name, x.iloc[train], rows.iloc[train][label])
            if reason:
                fallbacks.append({"fold": number, "method": name, "reason": reason,
                                  "replacement": "training-only median"})
            oof.loc[query, name] = np.maximum(model.predict(x.iloc[query]), 0)
        oof.loc[query, "fold"] = number
        oof.loc[query, "crop_seen_in_training"] = rows.iloc[query]["crop"].isin(rows.iloc[train]["crop"]).to_numpy()
        records.append({"fold": number, "train_row_ids": rows.iloc[train]["row_id"].tolist(),
                        "test_row_ids": rows.iloc[query]["row_id"].tolist(),
                        "train_facilities": int(rows.iloc[train]["facility_id"].nunique()),
                        "test_facilities": int(rows.iloc[query]["facility_id"].nunique()), "facility_overlap": False})
    metrics = {name: {**scores(rows[label], oof[name]),
                     "by_fold": {str(fold): scores(group[label], group[name]) for fold, group in oof.groupby("fold")},
                     "by_crop": {str(crop): scores(rows.loc[group.index, label], group[name])
                                 for crop, group in oof.groupby(rows["crop"])}}
               for name in METHODS}
    selected = min(METHODS, key=lambda name: metrics[name]["mae"])
    model, final_fallback = fit_cpu(selected, x, rows[label])
    bundle = {**provenance, "target": target, "target_column": label, "unit": unit,
              "features": FEATURES, "selected_cpu_model": selected, "model": model,
              "selected_model_fallback": final_fallback,
              "training_crops": sorted(rows["crop"].unique().tolist()), "training_rows": len(rows),
              "selection": "lowest same-row facility-group OOF MAE; no untouched final test"}
    summary = {"status": "completed", "target_column": label, "unit": unit, "rows": len(rows),
               "facilities": int(rows["facility_id"].nunique()), "zero_target_rows": int(rows[label].eq(0).sum()),
               "unseen_crop_oof_rows": int((~oof["crop_seen_in_training"]).sum()),
               "folds": records, "models": metrics, "selected_cpu_model": selected,
               "constant_training_fallbacks": fallbacks, "selected_model_fallback": final_fallback}
    return bundle, oof, summary


def predict_plans(bundle: dict, plans: pd.DataFrame) -> pd.DataFrame:
    """Use only a locally generated, trusted bundle; preserve training-data kind."""
    require_model_confirmation(bundle)
    if set(plans.columns) - set(FEATURES + ["plan_id"]):
        raise ValueError("Plans may contain only the seven planned features and optional plan_id")
    if bundle["features"] != FEATURES:
        raise ValueError("Artifact feature contract differs")
    x = features(plans)
    if not set(x["crop"]).issubset(bundle["training_crops"]):
        raise ValueError("A planned crop is absent from the training cohort")
    values = np.maximum(np.asarray(bundle["model"].predict(x), dtype=float), 0)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite plan predictions")
    result = pd.DataFrame({"plan_id": plans.get("plan_id", pd.Series(range(len(plans)), index=plans.index)),
                           "target": bundle["target"], "prediction": values, "unit": bundle["unit"]})
    for name in ["data_kind", "target_assumption", "source_manifest_sha256", "selected_cpu_model",
                 "target_period_evidence_sha256", "training_cohort_sha256", "candidate_sha256"]:
        result[name] = bundle[name]
    result["target_period_confirmed"] = bundle["target_period_confirmed"]
    result["interpretation"] = ("SYNTHETIC RUNTIME DEMO: not farm performance" if
        bundle["data_kind"] == "synthetic_schema_fixture" else
        "Document-backed cycle-period review; not independent provider verification or annual economics validation")
    return result

'''[1:-1], "\n", False, "8b65fca802d6e3c03453d5fccab37b478669e12e7220a8ff29e773980467bde3")

# ===== SOURCE FILE: src/dsz_observations.py =====
_save_source("src/dsz_observations.py", r'''
"""Cycle-safe DSZ observations available at a fixed elapsed-day cutoff."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd

from src.dsz_data import FEATURES, load_schema, load_tables, parse_date, validate_table

ENVIRONMENT = {
    "inside_temperature_c": "INR_TMPRT_MRCNT",
    "inside_humidity_pct": "INR_HMDT_MRCNT",
    "co2_ppm": "INR_CO2_QTY_MRCNT",
    "outside_temperature_c": "EXTRNL_TMPRT_MRCNT",
}
GROWTH = {
    "height_mm": "FLVS_MMUNT_MRCNT",
    "crown_diameter_mm": "DMTR_MMUNT_MRCNT",
    "fruit_count": "FSTNG_MRCNT",
}
WEATHER = {
    "max_temperature_c": "TOP_TMPRT_MSRVL",
    "min_temperature_c": "LOWST_TMPRT_MSRVL",
    "max_wind_speed_mps": "MAX_WNDSPD_MSRVL",
    "dewpoint_c": "DD_AVG_DWPTMP_MSRVL",
}
VALUE_FEATURES = (
    [f"env_{name}_{stat}" for name in ENVIRONMENT
     for stat in ("window_mean", "window_min", "window_max", "recent7_mean")]
    + [f"growth_{name}_{stat}" for name in GROWTH
       for stat in ("latest_mean", "visit_mean_delta")]
    + ["growth_week_latest_mean"]
    + [f"weather_{name}_window_mean" for name in WEATHER]
)
COVERAGE_FEATURES = [
    "env_observation_rows", "env_observed_days", "growth_visit_count",
    "growth_latest_sample_rows", "growth_days_since_latest_visit",
    "weather_observed_days", "weather_station_count", "alerts_published_row_count",
]
OBSERVATION_NUMERIC = VALUE_FEATURES + COVERAGE_FEATURES
KEYS = ["row_id", "facility_id", "cycle_id"]
OUTPUT_COLUMNS = KEYS + FEATURES + ["as_of"] + OBSERVATION_NUMERIC + ["has_observations"]
TIME_COLUMNS = {"DZ_001": "MSRM_DT", "DZ_003": "EXMN_YMD",
                "DZ_005": "OBSV_YMD", "DZ_006": "PRSTN_DT"}
DAILY_TABLES = {"DZ_003", "DZ_005"}


def load_observation_tables(input_dir: Path, encoding: str = "utf-8-sig") -> tuple[dict, list, list]:
    """Load exact schema columns; management outcomes are optional for queries."""
    schema = deepcopy(load_schema())
    schema["tables"]["DZ_004"]["required"] = False
    tables, sources = load_tables(input_dir, schema, encoding)
    issues = []
    for table_id, table in tables.items():
        tables[table_id], found = validate_table(table_id, table, schema["tables"][table_id])
        issues.extend(found)
    return tables, sources, issues


def _cycle_key(value: str) -> str | None:
    try:
        number = Decimal(value)
        return str(number.normalize()) if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _interval(row: pd.Series) -> tuple[datetime | None, datetime | None]:
    start = parse_date(row.FRMTM_BGNG_YMD, compact=True)
    end = parse_date(row.FRMTM_END_YMD, compact=True) if row.FRMTM_END_YMD else None
    return start, end + timedelta(days=1) if end else None


def _number(row: pd.Series, column: str) -> float:
    if column in row["_invalid_columns"] or not row[column]:
        return np.nan
    value = float(row[column])
    return value if np.isfinite(value) else np.nan


def _cycles(facilities: pd.DataFrame) -> dict:
    """Keep every raw row, even invalid ones, in identity/overlap checks."""
    by_facility = defaultdict(list)
    for index, row in facilities.iterrows():
        start, stop = _interval(row)
        by_facility[row.FCLT_ID].append({"index": index, "raw": row, "start": start,
                                       "stop": stop, "key": _cycle_key(row.FRMTM_SNO)})
    return by_facility


def _request_cycle(request: pd.Series, all_cycles: dict, cutoff_days: int) -> tuple[dict | None, str]:
    candidates = all_cycles.get(request.facility_id, [])
    cycle_key = _cycle_key(request.cycle_id)
    matches = [cycle for cycle in candidates if cycle["key"] == cycle_key] if cycle_key else []
    if len(matches) != 1:
        return None, "missing_or_nonunique_facility_cycle_key"
    selected = matches[0]
    row, start, stop = selected["raw"], selected["start"], selected["stop"]
    if row["_invalid_columns"] or row["_duplicate_key"]:
        return None, "invalid_facility_schema_or_duplicate_key"
    if not row.FCLT_ID or not row.ITEM_NM or not start:
        return None, "missing_facility_crop_or_start"
    if row.FRMTM_END_YMD and (stop is None or stop <= start):
        return None, "invalid_cycle_interval"
    if row.FRMTM_YR != str(start.year):
        return None, "cycle_year_disagrees_with_start"
    area = _number(row, "HTHS_SFC")
    if not np.isfinite(area) or area <= 0:
        return None, "missing_or_nonpositive_area"
    for other in candidates:
        if other["index"] == selected["index"]:
            continue
        other_start, other_stop = other["start"], other["stop"]
        if other_start is None or (other["raw"].FRMTM_END_YMD and
                                  (other_stop is None or other_stop <= other_start)):
            return None, "other_cycle_interval_unknown_for_facility"
        if (stop is None or other_start < stop) and (other_stop is None or start < other_stop):
            return None, "overlapping_cycles_in_raw_facility_table"
    as_of = start + timedelta(days=cutoff_days)
    if stop is not None and as_of >= stop:
        return None, "cutoff_after_cycle_end"
    return {**selected, "as_of": as_of}, ""


def _map_observations(tables: dict, all_cycles: dict, schema: dict) -> tuple[dict, dict]:
    """Map each source row once before producing any feature summaries."""
    mapped = defaultdict(lambda: defaultdict(list))
    excluded = {}
    for table_id, time_column in TIME_COLUMNS.items():
        reasons = Counter()
        excluded[table_id] = reasons
        if table_id not in tables:
            continue
        key_columns = {column["name"] for column in schema["tables"][table_id]["columns"]
                       if column["key"].startswith("PK")}
        for _, row in tables[table_id].iterrows():
            if row["_duplicate_key"] or row["_invalid_columns"] & (key_columns | {time_column}):
                reasons["invalid_or_duplicate_observation_key"] += 1
                continue
            time = parse_date(row[time_column], compact=table_id == "DZ_005")
            if not row.FCLT_ID or time is None:
                reasons["missing_facility_or_observation_time"] += 1
                continue
            if table_id in DAILY_TABLES:
                time = time.replace(hour=0, minute=0, second=0)
            candidates = all_cycles.get(row.FCLT_ID, [])
            matches = [cycle for cycle in candidates if cycle["start"] is not None
                       and cycle["start"] <= time and (cycle["stop"] is None or time < cycle["stop"])]
            if len(matches) != 1:
                reasons["no_unique_raw_cycle_at_observation_time"] += 1
                continue
            cycle = matches[0]
            if table_id in {"DZ_001", "DZ_003"} and row.FRMTM_YR != cycle["raw"].FRMTM_YR:
                reasons["observation_cycle_year_mismatch"] += 1
                continue
            available = time + timedelta(days=1) if table_id in DAILY_TABLES else time
            mapped[cycle["index"]][table_id].append({"raw": row, "time": time, "available": available})
    excluded["DZ_007"] = {"audit_only_no_publication_time": len(tables.get("DZ_007", []))}
    return mapped, {key: dict(value) for key, value in excluded.items()}


def _summarize(observations: dict, as_of: datetime, window_days: int) -> dict:
    result = dict.fromkeys(OBSERVATION_NUMERIC, np.nan)
    for name in COVERAGE_FEATURES:
        if name != "growth_days_since_latest_visit":
            result[name] = 0.0
    available = {table: [record for record in rows if record["available"] <= as_of]
                 for table, rows in observations.items()}
    lower = as_of - timedelta(days=window_days)
    env = available.get("DZ_001", [])
    window = [record for record in env if record["time"] > lower]
    recent = [record for record in env if record["time"] > as_of - timedelta(days=7)]
    result["env_observation_rows"] = float(len(window))
    result["env_observed_days"] = float(len({record["time"].date() for record in window}))
    for name, column in ENVIRONMENT.items():
        values = pd.Series([_number(record["raw"], column) for record in window], dtype=float)
        result[f"env_{name}_window_mean"] = float(values.mean())
        result[f"env_{name}_window_min"] = float(values.min())
        result[f"env_{name}_window_max"] = float(values.max())
        result[f"env_{name}_recent7_mean"] = float(pd.Series(
            [_number(record["raw"], column) for record in recent], dtype=float).mean())
    visits = defaultdict(list)
    for record in available.get("DZ_003", []):
        visits[record["time"]].append(record["raw"])
    dates = sorted(visits)
    result["growth_visit_count"] = float(len(dates))
    if dates:
        latest = visits[dates[-1]]
        previous = visits[dates[-2]] if len(dates) > 1 else []
        result["growth_latest_sample_rows"] = float(len(latest))
        result["growth_days_since_latest_visit"] = float((as_of - dates[-1]).days)
        for name, column in GROWTH.items():
            current_mean = float(pd.Series([_number(row, column) for row in latest], dtype=float).mean())
            previous_mean = float(pd.Series([_number(row, column) for row in previous], dtype=float).mean())
            result[f"growth_{name}_latest_mean"] = current_mean
            result[f"growth_{name}_visit_mean_delta"] = current_mean - previous_mean
        result["growth_week_latest_mean"] = float(pd.Series(
            [_number(row, "GRDV_NOFWK") for row in latest], dtype=float).mean())
    weather = [record for record in available.get("DZ_005", []) if record["time"] >= lower]
    result["weather_observed_days"] = float(len({record["time"] for record in weather}))
    result["weather_station_count"] = float(len({record["raw"].OBSV_PNT_CDCN for record in weather}))
    for name, column in WEATHER.items():
        day_values = defaultdict(list)
        for record in weather:
            day_values[record["time"]].append(_number(record["raw"], column))
        daily_means = [pd.Series(values, dtype=float).mean() for values in day_values.values()]
        result[f"weather_{name}_window_mean"] = float(pd.Series(daily_means, dtype=float).mean())
    result["alerts_published_row_count"] = float(sum(
        record["time"] > lower for record in available.get("DZ_006", [])))
    result["has_observations"] = any(np.isfinite(result[name]) for name in VALUE_FEATURES
                                     if name != "growth_week_latest_mean")
    return result


def build_observation_features(tables: dict, requests: pd.DataFrame, cutoff_days: int,
                               window_days: int = 28) -> tuple[pd.DataFrame, dict]:
    """Return one row per valid request; absent numeric observations stay NaN.

    Callers must separately verify the target period. An empty cycle end permits
    an ongoing query; it is not evidence of a complete training outcome period.
    """
    if isinstance(cutoff_days, bool) or not isinstance(cutoff_days, int) or cutoff_days < 0:
        raise ValueError("cutoff_days must be a nonnegative integer")
    if isinstance(window_days, bool) or not isinstance(window_days, int) or window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    if set(KEYS) - set(requests.columns):
        raise ValueError("Requests require row_id, facility_id and cycle_id")
    requests = requests[KEYS].copy()
    if requests.isna().any().any():
        raise ValueError("Request identifiers must not be missing")
    requests = requests.astype(str)
    if requests.eq("").any().any() or requests.row_id.duplicated().any():
        raise ValueError("Request identifiers must be nonempty and row_id unique")
    if "DZ_002" not in tables:
        raise ValueError("DZ_002 facilities are required")
    for table in tables.values():
        if not {"_invalid_columns", "_duplicate_key"}.issubset(table.columns) or not table.index.is_unique:
            raise ValueError("Use validated tables with unique row indices")
    schema = load_schema()
    all_cycles = _cycles(tables["DZ_002"])
    mapped, observation_exclusions = _map_observations(tables, all_cycles, schema)
    output, exclusions = [], []
    for _, request in requests.iterrows():
        cycle, reason = _request_cycle(request, all_cycles, cutoff_days)
        if cycle is None:
            exclusions.append({**request.to_dict(), "reason": reason})
            continue
        row = cycle["raw"]
        result = {**request.to_dict(), "crop": row.ITEM_NM, "region": row.AREA_NM,
                  "greenhouse_type": row.SACT_INTLCK_SPR_NM, "greenhouse_size": row.HTHS_SCL_CN,
                  "area_m2": _number(row, "HTHS_SFC"), "planned_start_year": cycle["start"].year,
                  "planned_start_month": cycle["start"].month, "as_of": cycle["as_of"].isoformat()}
        result.update(_summarize(mapped.get(cycle["index"], {}), cycle["as_of"], window_days))
        output.append(result)
    frame = pd.DataFrame(output, columns=OUTPUT_COLUMNS)
    audit = {
        "cutoff_days": cutoff_days, "window_days": window_days, "requested_rows": len(requests),
        "accepted_rows": len(frame), "excluded_requests": exclusions,
        "table_rows": {table_id: len(table) for table_id, table in tables.items()},
        "observation_exclusions": observation_exclusions,
        "assumptions": [
            "Observation/publication timestamp is assumed availability; actual arrival latency is unverified.",
            "Daily growth/weather observations become available the following midnight; cutoff-day rows are excluded.",
            "STR_DT is bulk loading time and is never a cutoff feature.",
            "Growth deltas compare sample means at two visits, not tracked individual plants.",
            "Weather uses declared facility-to-station links; station means per day precede equally weighted day means.",
            "Environment means weight recorded readings equally; missing numbers remain NaN, not zero.",
            "Coverage counts count available source rows/days, not certified measurement completeness.",
            "Alert count is published source rows, not distinct weather events; absence does not prove no event.",
            "Typhoon OBSV_DT has no publication time; typhoon records are audit-only.",
            "Wind direction, rainfall and sunlight accumulation are excluded pending semantic verification.",
            "Blank cycle end supports ongoing queries only; training target completeness needs separate evidence.",
        ],
    }
    return frame, audit

'''[1:-1], "\n", False, "1d6e8ebc4c6f8d3f6594888c7253f04fbf3e4766a91ec56a3db934ca986f630e")

# ===== SOURCE FILE: src/dsz_period.py =====
_save_source("src/dsz_period.py", r'''
"""Documented management-period checks; declarations are not independent audits."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re


TARGET_COLUMNS = {"ALL_SHPMNT_KGUNT_QTY", "ALL_INCM_AMT"}
POLICIES = {"single_record_per_cycle", "incremental_sum", "latest_cumulative"}


def evidence_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_digest(value: dict) -> str:
    return hashlib.sha256(evidence_json(value).encode("utf-8")).hexdigest()


def _date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Period evidence dates must be YYYY-MM-DD")
    return date.fromisoformat(value)


def _header(proof: dict, policy: str, data_kind: str) -> None:
    if proof.get("schema_version") != 1 or proof.get("policy") != policy or policy not in POLICIES:
        raise ValueError("Period evidence policy differs from selected management policy")
    if proof.get("data_kind") != data_kind:
        raise ValueError("Period evidence data kind differs; synthetic evidence cannot confirm real data")
    if set(proof.get("target_columns", [])) != TARGET_COLUMNS:
        raise ValueError("Period evidence must define both shipment and revenue aggregation")
    definition = proof.get("definition", {})
    for name in ["path", "locator", "reviewed_by", "reviewed_at", "aggregation_definition"]:
        if not isinstance(definition.get(name), str) or not definition[name].strip():
            raise ValueError(f"Period evidence requires definition {name}")
    _date(definition["reviewed_at"])
    if not re.fullmatch(r"[0-9a-f]{64}", str(definition.get("sha256", ""))):
        raise ValueError("Period evidence requires definition document SHA256")
    sources = proof.get("source_files", [])
    if {item.get("dataset") for item in sources} != {"DZ_002", "DZ_004"} or len(sources) != 2:
        raise ValueError("Period evidence requires exact facility and management source hashes")
    for item in sources:
        if not item.get("file") or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise ValueError("Period evidence has incomplete source identity")


def validate_cycle(proof: dict, *, policy: str, data_kind: str) -> None:
    """Require the declared intervals to cover one whole cycle under the policy."""
    _header(proof, policy, data_kind)
    cycle = proof.get("cycle", {})
    if not cycle.get("facility_id") or not cycle.get("cycle_id"):
        raise ValueError("Period evidence requires facility and cycle identity")
    start, end = _date(cycle["start"]), _date(cycle["end"])
    records = cycle.get("records", [])
    if end < start or not records:
        raise ValueError("Period evidence requires a valid cycle and management records")
    source_rows = [record.get("source_row") for record in records]
    if any(type(row) is not int or row < 2 for row in source_rows) or len(set(source_rows)) != len(source_rows):
        raise ValueError("Period evidence management source rows must be unique CSV/Excel row numbers")
    intervals = sorted((_date(record["start"]), _date(record["end"])) for record in records)
    if any(left < start or right > end or right < left for left, right in intervals):
        raise ValueError("Period evidence interval is outside its facility cycle")
    if policy == "single_record_per_cycle":
        if intervals != [(start, end)]:
            raise ValueError("Single management record must document the full cycle period")
    elif policy == "incremental_sum":
        cursor = start
        for left, right in intervals:
            if left != cursor:
                raise ValueError("Incremental periods must cover the full cycle without gaps or overlap")
            cursor = right + timedelta(days=1)
        if cursor != end + timedelta(days=1):
            raise ValueError("Incremental periods do not cover the full cycle")
    else:
        if any(left != start for left, _ in intervals) or max(right for _, right in intervals) != end:
            raise ValueError("Cumulative records must start at cycle start and include a final cycle-total record")
        if sum(right == end for _, right in intervals) != 1:
            raise ValueError("Cumulative evidence requires exactly one final cycle-total record")


def load_confirmation(path: Path | None, sources: list[dict], *, policy: str, data_kind: str) -> dict | None:
    if path is None:
        return None
    declaration = json.loads(path.read_text(encoding="utf-8"))
    _header(declaration, policy, data_kind)
    expected = [{key: item[key] for key in ["dataset", "file", "sha256"]}
                for item in sources if item["dataset"] in {"DZ_002", "DZ_004"}]
    if sorted(declaration["source_files"], key=lambda x: x["dataset"]) != sorted(expected, key=lambda x: x["dataset"]):
        raise ValueError("Period evidence source hashes differ from the actual input files")
    definition = declaration["definition"]
    document = Path(definition["path"])
    if not document.is_absolute():
        document = path.parent / document
    if not document.is_file() or hashlib.sha256(document.read_bytes()).hexdigest() != definition["sha256"]:
        raise ValueError("Period definition document is missing or its SHA256 differs")
    identities, assigned_rows = set(), set()
    management_rows = next(item["rows"] for item in sources if item["dataset"] == "DZ_004")
    for cycle in declaration.get("cycles", []):
        identity = (cycle.get("facility_id"), cycle.get("cycle_id"))
        if identity in identities:
            raise ValueError("Duplicate cycle in period evidence")
        identities.add(identity)
        validate_cycle({**declaration, "cycle": cycle}, policy=policy, data_kind=data_kind)
        for record in cycle["records"]:
            if record["source_row"] in assigned_rows:
                raise ValueError("A management source row cannot be assigned to multiple cycles")
            if record["source_row"] > management_rows + 1:
                raise ValueError("Period evidence management source row is outside the input file")
            assigned_rows.add(record["source_row"])
    return declaration


def candidate_proof(declaration: dict | None, facility, surveys: list, policy: str, data_kind: str) -> dict | None:
    if declaration is None:
        return None
    matches = [cycle for cycle in declaration.get("cycles", [])
               if (cycle["facility_id"], cycle["cycle_id"]) == (facility["FCLT_ID"], facility["FRMTM_SNO"])]
    if not matches:
        return None
    proof = {key: value for key, value in declaration.items() if key != "cycles"}
    proof["cycle"] = matches[0]
    validate_cycle(proof, policy=policy, data_kind=data_kind)
    cycle = proof["cycle"]
    if cycle["start"].replace("-", "") != facility["FRMTM_BGNG_YMD"] or cycle["end"].replace("-", "") != facility["FRMTM_END_YMD"]:
        raise ValueError("Period evidence cycle dates differ from facility source")
    if {record["source_row"] for record in cycle["records"]} != {int(row["_source_row"]) for row in surveys}:
        raise ValueError("Period evidence must identify every matched management source row")
    by_row = {int(row["_source_row"]): row for row in surveys}
    if any(record["end"].replace("-", "") > by_row[record["source_row"]]["EXMN_YMD"] for record in cycle["records"]):
        raise ValueError("Management survey precedes the declared end of its observed period")
    if policy == "latest_cumulative":
        latest = max(surveys, key=lambda row: row["EXMN_YMD"])
        final = next(record for record in cycle["records"] if record["end"] == cycle["end"])
        if final["source_row"] != int(latest["_source_row"]):
            raise ValueError("Latest survey is not the documented final cumulative record")
    return proof


def require_confirmed_rows(rows) -> None:
    """Reject old candidates and bare boolean assertions before model fitting."""
    required = {"target_period_confirmed", "target_period_evidence_json", "target_period_evidence_sha256"}
    if required - set(rows.columns):
        raise ValueError("Target period confirmation evidence is missing; candidates are audit-only")
    if not rows["target_period_confirmed"].eq(True).all():
        raise ValueError("Unconfirmed target period; candidates are audit-only and cannot train a model")
    for row in rows.to_dict("records"):
        try:
            proof = json.loads(row["target_period_evidence_json"])
            validate_cycle(proof, policy=row["target_assumption"], data_kind=row["data_kind"])
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise ValueError("Invalid target period evidence") from error
        if evidence_digest(proof) != row["target_period_evidence_sha256"]:
            raise ValueError("Target period evidence SHA256 differs")
        if (proof["cycle"]["facility_id"], proof["cycle"]["cycle_id"]) != (str(row["facility_id"]), str(row["cycle_id"])):
            raise ValueError("Target period evidence belongs to another facility or cycle")


def require_model_confirmation(provenance: dict) -> None:
    evidence = provenance.get("target_period_evidence_sha256")
    if provenance.get("target_period_confirmed") is not True or not isinstance(evidence, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence):
        raise ValueError("Model requires documented target period confirmation; annual assumptions cannot replace it")
    declaration = provenance.get("target_period_confirmation")
    if not isinstance(declaration, dict) or evidence_digest(declaration) != evidence or not declaration.get("cycles"):
        raise ValueError("Model requires the matching period definition and per-cycle evidence declaration")
    for cycle in declaration["cycles"]:
        validate_cycle({**declaration, "cycle": cycle}, policy=provenance["target_assumption"], data_kind=provenance["data_kind"])
    cohort = provenance.get("training_cohort")
    if not isinstance(cohort, dict) or evidence_digest(cohort) != provenance.get("training_cohort_sha256"):
        raise ValueError("Training cohort selection evidence is missing or its SHA256 differs")
    names = ["candidate_rows", "used_rows", "unconfirmed_excluded_rows", "confirmed_ineligible_excluded_rows"]
    if any(type(cohort.get(name)) is not int or cohort[name] < 0 for name in names):
        raise ValueError("Training cohort selection counts are invalid")
    if cohort["used_rows"] < 1 or cohort["candidate_rows"] != sum(cohort[name] for name in names[1:]):
        raise ValueError("Training cohort selection counts do not reconcile")
    if cohort.get("source_all_periods_confirmed") != (cohort["unconfirmed_excluded_rows"] == 0):
        raise ValueError("Training cohort source confirmation status disagrees with excluded rows")
    for name in ["source_manifest_sha256", "candidate_sha256"]:
        if cohort.get(name) != provenance.get(name):
            raise ValueError("Training cohort selection differs from its original input provenance")
    if not re.fullmatch(r"[0-9a-f]{64}", str(cohort.get("source_period_evidence_sha256", ""))):
        raise ValueError("Training cohort lacks original period declaration SHA256")
    records = cohort.get("used_candidates", [])
    identities = [(record.get("facility_id"), record.get("cycle_id")) for record in records]
    if len(records) != cohort["used_rows"] or len(set(identities)) != len(records) or len({record.get("row_id") for record in records}) != len(records):
        raise ValueError("Training cohort selected identities are missing or duplicated")
    proofs = {}
    for cycle in declaration["cycles"]:
        proof = {key: value for key, value in declaration.items() if key != "cycles"}
        proof["cycle"] = cycle
        proofs[(cycle["facility_id"], cycle["cycle_id"])] = evidence_digest(proof)
    if set(identities) != set(proofs):
        raise ValueError("Training cohort identities differ from confirmed cycle evidence")
    for record, identity in zip(records, identities, strict=True):
        if record.get("target_period_evidence_sha256") != proofs[identity]:
            raise ValueError("Training cohort row period evidence differs from declaration")

'''[1:-1], "\n", False, "537ad345e11c55359c4f6e7ee67af06fdcf14ef15c1f2d50e06c7812fb2a17f0")

print("준비 완료:", DSZ_ROOT)
print("내장 파일 복원 및 SHA256 확인:", len(_SAVED_SOURCE_FILES), "개")

# ===== 입력 연결 및 실행 폴더 =====
import csv

if MODE == "demo":
    HISTORY_DIR = DSZ_ROOT / "data/examples/dsz_inseason/input"
    PERIOD_CONFIRMATION = HISTORY_DIR / "period_confirmation.json"
    CURRENT_DIR = DSZ_ROOT / "data/examples/dsz_inseason/query"
    REQUESTS_CSV = DSZ_ROOT / "data/examples/dsz_inseason/requests.csv"
    ENCODING = "utf-8-sig"
    MANAGEMENT_POLICY = "single_record_per_cycle"
elif MODE == "real":
    if REAL_HISTORY_DIR is None:
        raise ValueError("REAL_HISTORY_DIR에 실제 원자료 폴더 경로를 지정하세요.")
    HISTORY_DIR = Path(REAL_HISTORY_DIR).expanduser().resolve()
    PERIOD_CONFIRMATION = Path(REAL_PERIOD_CONFIRMATION).expanduser().resolve() if REAL_PERIOD_CONFIRMATION is not None else None
    if not isinstance(TARGET_FACILITY_ID, str) or not isinstance(TARGET_CYCLE_ID, str):
        raise ValueError("시설ID·작기ID는 따옴표로 감싼 문자열로 입력하세요.")
    if bool(TARGET_FACILITY_ID) != bool(TARGET_CYCLE_ID):
        raise ValueError("TARGET_FACILITY_ID와 TARGET_CYCLE_ID를 둘 다 입력하세요.")
    if REAL_CURRENT_DIR is not None and not TARGET_FACILITY_ID:
        raise ValueError("예측 대상 폴더를 지정했다면 시설ID와 작기ID도 입력하세요.")
    CURRENT_DIR = (Path(REAL_CURRENT_DIR).expanduser().resolve() if REAL_CURRENT_DIR is not None else HISTORY_DIR) if TARGET_FACILITY_ID else None
    REQUESTS_CSV = None
else:
    raise ValueError('MODE는 "demo" 또는 "real"이어야 합니다.')

if not HISTORY_DIR.is_dir():
    raise FileNotFoundError(HISTORY_DIR)
if PERIOD_CONFIRMATION is not None and not PERIOD_CONFIRMATION.is_file():
    raise FileNotFoundError(PERIOD_CONFIRMATION)
if CURRENT_DIR is not None and not CURRENT_DIR.is_dir():
    raise FileNotFoundError(CURRENT_DIR)

RUN_DIR = DSZ_ROOT / "runs" / (MODE + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
RUN_DIR.mkdir(parents=True, exist_ok=False)
if MODE == "real" and CURRENT_DIR is not None:
    REQUESTS_CSV = RUN_DIR / "requests.csv"
    with REQUESTS_CSV.open("x", encoding=ENCODING, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["plan_id", "facility_id", "cycle_id"])
        writer.writerow(["user_plan", TARGET_FACILITY_ID, TARGET_CYCLE_ID])
if REQUESTS_CSV is not None and not REQUESTS_CSV.is_file():
    raise FileNotFoundError(REQUESTS_CSV)
print("실행 종류:", MODE, "/ 원자료 폴더:", HISTORY_DIR)
print("결과 폴더:", RUN_DIR)


def run_step(*arguments):
    # 현재 노트북의 Python으로 새 프로세스를 실행합니다.
    # 모듈의 __file__ 경로와 argparse가 노트북 내부 인자에 영향을 받지 않습니다.
    command = [sys.executable, "-X", "utf8", *map(str, arguments)]
    print("실행:", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=DSZ_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    result.check_returncode()

# %% 3. 실제 명세서 열 이름·타입·시설 연결 및 총출하량 집계기간 검사
prepare_args = [
    "scripts/prepare_dsz.py",
    "--input-dir", HISTORY_DIR,
    "--output-dir", RUN_DIR / "prepared",
    "--encoding", ENCODING,
    "--management-policy", MANAGEMENT_POLICY,
]
if PERIOD_CONFIRMATION is not None:
    prepare_args += ["--period-confirmation", PERIOD_CONFIRMATION]
run_step(*prepare_args)

READY_TO_TRAIN = PERIOD_CONFIRMATION is not None
if not READY_TO_TRAIN:
    print("자료 검사는 완료했습니다. 총출하량의 실제 집계기간 근거가 없어 학습은 보류합니다.")
    print("prepared 폴더의 검사 결과와 reports/dsz_schema_contract.md를 확인하세요.")
    print("실제 정의 근거로 기간 확인 JSON을 작성한 뒤, 상단 경로를 지정하고 이 파일을 다시 실행하세요.")

# %% 4. 같은 시설이 학습·검증에 겹치지 않도록 출하량 모델 비교
# 기본 7개 입력과 관측 요약을 추가한 입력을 같은 시설·작기에서 비교합니다.
# 비교: 품목 중앙값, 면적 기준 중앙값, CatBoost, XGBoost.
# LimiX-2와 경제성 계산은 이 실행 경로에 포함되지 않습니다.
if READY_TO_TRAIN:
    run_step(
        "scripts/run_dsz_inseason.py", "train",
        "--data-dir", RUN_DIR / "prepared",
        "--input-dir", HISTORY_DIR,
        "--output-dir", RUN_DIR / "models",
        "--cutoff-days", CUTOFF_DAYS,
        "--window-days", WINDOW_DAYS,
        "--crop", CROP,
        "--encoding", ENCODING,
    )
    metrics = json.loads((RUN_DIR / "models/dsz_inseason_metrics.json").read_text(encoding="utf-8"))
    print("학습·검증 요약:")
    print(json.dumps({key: metrics.get(key) for key in ["status", "data_kind", "rows", "facilities", "selected_methods"]}, ensure_ascii=False, indent=2))
    print("전체 비교 결과:", RUN_DIR / "models/dsz_inseason_metrics.json")
    if MODE == "demo":
        print("주의: 합성 예제 실행 결과입니다. 실제 출하량 예측 성능이 아닙니다.")

# %% 5. 지정한 시설·작기의 예측일까지 관측을 연결해 총출하량 예측
if READY_TO_TRAIN and CURRENT_DIR is not None:
    run_step(
        "scripts/run_dsz_inseason.py", "predict",
        "--artifact-dir", RUN_DIR / "models",
        "--input-dir", CURRENT_DIR,
        "--requests", REQUESTS_CSV,
        "--output", RUN_DIR / "predictions.csv",
        "--encoding", ENCODING,
    )
    import pandas as pd
    predictions = pd.read_csv(RUN_DIR / "predictions.csv", encoding="utf-8-sig", dtype={"facility_id": str, "cycle_id": str})
    print(predictions[["facility_id", "cycle_id", "as_of", "prediction", "unit"]].rename(columns={"facility_id": "시설ID", "cycle_id": "작기ID", "as_of": "예측기준시각", "prediction": "예상_작기총출하량", "unit": "단위"}).to_string(index=False))
    if MODE == "real":
        print("학습에 사용된 시설의 재예측은 독립 검증 성능이 아닙니다.")
    print("결과:", RUN_DIR / "predictions.csv")
    print("출하량은 해당 작기 전체 kg입니다. 남은 출하량·소득·투자 회수기간·설비 도입 효과가 아닙니다.")
elif READY_TO_TRAIN:
    print("학습 완료. 상단 TARGET_FACILITY_ID와 TARGET_CYCLE_ID를 지정하면 예측까지 실행할 수 있습니다.")

print("이번 실행의 모든 결과 폴더:", RUN_DIR)
