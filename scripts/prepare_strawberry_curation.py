"""Preserve and audit the official strawberry curation without summing shipment rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/smartfarm_curation"
HEADERS = {
    "shipping": ["시설ID", "작기명", "품목", "품종", "정식시작일", "정식종료일", "총출하수량",
                 "최상등급수량", "상등급수량", "중등급수량", "하등급수량", "수익금액"],
    "growth": ["시설ID", "품목", "품종명", "조사주차", "조사일자", "표본번호", "항목명", "측정값", "단위"],
    "environment": ["시설ID", "작기명", "품목", "품종", "정식시작일", "정식종료일", "분석일자",
                    "내부일평균온도", "내부주간온도", "내부야간온도", "주야간온도차", "내부평균습도",
                    "CO2농도", "배액EC", "배액pH"],
}
FILENAMES = {"shipping": "작기_출하량데이터.xlsx", "growth": "작기_생육데이터.xlsx",
             "environment": "작기_환경데이터.xlsx"}
FEATURE_COLUMNS = ["variety", "planting_month", "planting_day", "area_m2", "region_sido",
                   "region_sigungu", "facility_type", "cultivation_method", "greenhouse_type"]


class PreparationError(ValueError):
    """The source or its declared integrity could not be verified."""


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def serialize(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def number(value) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date() if value.time().isoformat() == "00:00:00" else None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value) if len(value) == 10 else None
        except ValueError:
            pass
    return None


def read_source(zip_path: Path, acquisition_path: Path) -> tuple[dict, dict]:
    content = zip_path.read_bytes()
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    if (acquisition.get("sha256") != digest(content) or acquisition.get("bytes") != len(content)
            or acquisition.get("file") != zip_path.name or not acquisition.get("acquired")):
        raise PreparationError("ZIP acquisition hash, size, filename or acquired flag mismatch")
    tables, members = {}, {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise PreparationError("ZIP CRC failure")
        for table, filename in FILENAMES.items():
            matches = [name for name in archive.namelist() if name.rsplit("/", 1)[-1] == filename]
            if len(matches) != 1:
                raise PreparationError(f"Expected exactly one workbook: {filename}")
            member = matches[0]
            workbook_bytes = archive.read(member)
            workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=False)
            try:
                if len(workbook.worksheets) != 1:
                    raise PreparationError(f"Unexpected sheet count in {filename}")
                sheet = workbook.worksheets[0]
                iterator = sheet.iter_rows()
                headers = [cell.value for cell in next(iterator)]
                if headers != HEADERS[table]:
                    raise PreparationError(f"Unexpected columns in {filename}: {headers}")
                rows = []
                for row_number, cells in enumerate(iterator, 2):
                    if any(cell.data_type == "f" for cell in cells):
                        raise PreparationError(f"Formula requires explicit review: {filename}:{row_number}")
                    raw = dict(zip(headers, [cell.value for cell in cells], strict=True))
                    rows.append({**raw, "source_record_id": f"{table}:{row_number}",
                                 "source_zip_sha256": digest(content), "source_member": member,
                                 "source_member_sha256": digest(workbook_bytes), "source_sheet": sheet.title,
                                 "source_excel_row": row_number,
                                 "source_raw_record_json": canonical({k: serialize(v) for k, v in raw.items()})})
                tables[table] = rows
                members[table] = {"member": member, "sha256": digest(workbook_bytes), "bytes": len(workbook_bytes),
                                  "sheet": sheet.title, "rows": len(rows), "headers": headers}
            finally:
                workbook.close()
    return tables, {"zip_path": str(zip_path.resolve()), "zip_sha256": digest(content),
                    "acquisition_path": str(acquisition_path.resolve()),
                    "acquisition_sha256": digest(acquisition_path.read_bytes()), "members": members}


def read_api_metadata(directory: Path) -> tuple[list[dict], list[dict], dict]:
    audit_path = directory / "smartfarm_api_audit.json"
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    tables, evidence = {}, {"audit_sha256": digest(audit_bytes), "source_run_id": audit["source_run_id"]}
    for table in ("cycles", "catalog"):
        filename = f"smartfarm_api_{table}.csv"
        content = (directory / filename).read_bytes()
        declared = audit["output_files"][filename]
        if digest(content) != declared["sha256"] or len(content) != declared["bytes"]:
            raise PreparationError(f"API metadata hash mismatch: {filename}")
        tables[table] = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        evidence[filename] = declared
    return tables["cycles"], tables["catalog"], evidence


def metadata_match(row: dict, cycle_index: dict, catalog_index: dict) -> dict:
    start, end = parse_date(row.get("정식시작일")), parse_date(row.get("정식종료일"))
    key = (row.get("시설ID"), start.isoformat() if start else None,
           end.isoformat() if end else None, row.get("품목"))
    matches = cycle_index.get(key, [])
    result = {"metadata_match_status": "unknown_no_exact_cycle", "api_cycle_match_count": len(matches),
              "api_cycle_source_ids": canonical([r["source_record_id"] for r in matches])}
    if len(matches) != 1:
        if matches:
            result["metadata_match_status"] = "conflict_multiple_exact_cycles"
        return result
    cycle = matches[0]
    catalogs = catalog_index.get((cycle["fcltyId"], cycle["crpsnSn"], cycle["fcltyYear"]), [])
    result["api_catalog_source_ids"] = canonical([r["source_record_id"] for r in catalogs])
    if len(catalogs) != 1:
        result["metadata_match_status"] = "conflict_or_missing_catalog"
        return result
    catalog = catalogs[0]
    area, catalog_area = number(cycle.get("ctvtAr")), number(catalog.get("ctvtAr"))
    result.update(api_cycle_area_raw=cycle.get("ctvtAr"), api_catalog_area_raw=catalog.get("ctvtAr"))
    if cycle.get("itemCodeNm") != catalog.get("itemCodeNm") or cycle.get("itemCode") != catalog.get("itemCode"):
        result["metadata_match_status"] = "conflict_crop_metadata"
    elif cycle.get("spciesCodeNm") != row.get("품종") or catalog.get("spciesCodeNm") != row.get("품종"):
        result["metadata_match_status"] = "conflict_variety_metadata"
    elif area is None or catalog_area is None:
        result["metadata_match_status"] = "matched_area_missing_or_invalid"
    elif area != catalog_area:
        result["metadata_match_status"] = "conflict_area_metadata"
    elif area <= 0:
        result["metadata_match_status"] = "matched_area_nonpositive"
    else:
        result.update(metadata_match_status="matched_positive_area", area_m2=area,
                      region_sido=catalog.get("fcltySidoCodeNm"), region_sigungu=catalog.get("fcltySigunguCodeNm"),
                      facility_type=catalog.get("fcltyTyCodeNm"), cultivation_method=catalog.get("ctvtMthdCodeNm"),
                      greenhouse_type=catalog.get("scspnMltspnSeCodeNm"))
    return result


def normalize_shipping(rows: list[dict], cycles: list[dict], catalog: list[dict], as_of: date) -> list[dict]:
    period_index, named_index, cycle_index, catalog_index = (defaultdict(list) for _ in range(4))
    for row in rows:
        period_index[(row.get("시설ID"), row.get("품목"), parse_date(row.get("정식시작일")),
                      parse_date(row.get("정식종료일")))].append(row)
        named_index[(row.get("시설ID"), row.get("작기명"))].append(row)
    for row in cycles:
        cycle_index[(row["fcltyId"], row["fixplntngDe"], row["crpsnEndDe"], row["itemCodeNm"])].append(row)
    for row in catalog:
        catalog_index[(row["fcltyId"], row["crpsnSn"], row["fcltyYear"])].append(row)
    normalized = []
    for original in rows:
        row, reasons, flags = dict(original), [], []
        facility, crop, quantity = row.get("시설ID"), row.get("품목"), number(row.get("총출하수량"))
        start, end = parse_date(row.get("정식시작일")), parse_date(row.get("정식종료일"))
        if not facility or not row.get("작기명"):
            reasons.append("missing_facility_or_cycle_identity")
        if crop != "딸기":
            reasons.append("unexpected_crop")
        if not row.get("품종"):
            reasons.append("missing_variety")
        if start is None or end is None:
            reasons.append("missing_or_invalid_cycle_date")
        elif end <= start:
            reasons.append("nonpositive_cycle_duration")
        else:
            row["cycle_duration_days_audit_only"] = (end - start).days
            if (end - start).days > 366:
                reasons.append("cycle_longer_than_366_days_review")
            if start > as_of or end > as_of:
                reasons.append("future_or_not_yet_ended_cycle")
        if quantity is None:
            reasons.append("missing_or_invalid_quantity")
        elif quantity <= 0:
            reasons.append("zero_quantity_meaning_unknown" if quantity == 0 else "negative_quantity")
        if quantity is not None and quantity >= 1_000_000:
            flags.append("million_kg_scale_review_no_automatic_correction")
        same_period = period_index[(facility, crop, start, end)]
        row["same_period_row_count"] = len(same_period)
        if len(same_period) > 1:
            raw_count = len({r["source_raw_record_json"] for r in same_period})
            reasons.append("duplicate_identical_period_rows" if raw_count == 1 else "conflicting_period_rows")
        same_name = named_index[(facility, row.get("작기명"))]
        periods = {(parse_date(r.get("정식시작일")), parse_date(r.get("정식종료일"))) for r in same_name}
        if len(periods) > 1:
            reasons.append("same_named_cycle_conflicting_periods")
        grade_values = [number(row.get(name)) for name in HEADERS["shipping"][7:11]]
        if all(value is not None for value in grade_values):
            grade_sum = sum(grade_values)
            row["grade_sum_kg_audit_only"] = grade_sum
            if quantity is not None and grade_sum > quantity:
                flags.append("grade_sum_exceeds_total")
            elif quantity is not None and quantity > 0 and grade_sum == 0:
                flags.append("positive_total_all_grades_zero_meaning_unknown")
            elif quantity is not None and grade_sum < quantity:
                flags.append("grade_sum_below_total")
        row.update(farm_group=facility, variety=row.get("품종"),
                   planting_date=start.isoformat() if start else None,
                   planting_year=start.year if start else None,
                   planting_month=start.month if start else None, planting_day=start.day if start else None,
                   reported_cycle_total_kg=quantity, target_unit="kg_per_reported_crop_cycle",
                   target_candidate=not reasons, exclusion_reasons=canonical(reasons),
                   quality_flags=canonical(flags), completeness_verified=False)
        row.update(metadata_match(row, cycle_index, catalog_index))
        row["pre_adoption_metadata_eligible"] = not reasons and row["metadata_match_status"] == "matched_positive_area"
        if row["pre_adoption_metadata_eligible"]:
            row["reported_cycle_kg_per_m2"] = quantity / row["area_m2"]
        normalized.append(row)
    return normalized


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: serialize(v) for k, v in row.items()} for row in rows)


def prepare(zip_path: Path, acquisition_path: Path, api_directory: Path, output_directory: Path,
            as_of: date, report_path: Path | None = None) -> dict:
    tables, evidence = read_source(zip_path, acquisition_path)
    cycles, catalog, api_evidence = read_api_metadata(api_directory)
    shipping = normalize_shipping(tables["shipping"], cycles, catalog, as_of)
    tables["shipping"] = shipping
    candidates = [row for row in shipping if row["target_candidate"]]
    metadata_candidates = [row for row in shipping if row["pre_adoption_metadata_eligible"]]
    exclusion_counts, flag_counts = Counter(), Counter()
    for row in shipping:
        exclusion_counts.update(json.loads(row["exclusion_reasons"]))
        flag_counts.update(json.loads(row["quality_flags"]))
    audit = {"as_of_date": as_of.isoformat(), "source": evidence, "api_metadata_source": api_evidence,
             "tables": {name: {"rows": len(rows), "facilities": len({r.get("시설ID") for r in rows}),
                               "missing_values": {h: sum(r.get(h) is None for r in rows) for h in HEADERS[name]}}
                        for name, rows in tables.items()},
             "shipping_positive_rows": sum((number(r.get("총출하수량")) or 0) > 0 for r in shipping),
             "target_candidate_rows": len(candidates), "target_candidate_facilities": len({r["farm_group"] for r in candidates}),
             "metadata_candidate_rows": len(metadata_candidates),
             "metadata_candidate_facilities": len({r["farm_group"] for r in metadata_candidates}),
             "candidate_planting_year_counts": dict(Counter(r["planting_year"] for r in candidates)),
             "candidate_variety_counts": dict(Counter(r["variety"] for r in candidates)),
             "exclusion_counts": dict(exclusion_counts), "quality_flag_counts": dict(flag_counts),
             "metadata_match_counts": dict(Counter(r["metadata_match_status"] for r in shipping)),
             "positive_metadata_match_counts": dict(Counter(r["metadata_match_status"] for r in shipping
                                                             if (r["reported_cycle_total_kg"] or 0) > 0)),
             "target": "officially defined reported crop-cycle shipment total, kg; not independently certified full harvest",
             "area_unit": "m2 from exactly matched API crop-cycle and catalog; absent in curation source",
             "feature_columns": FEATURE_COLUMNS,
             "forbidden_features": ["facility_id", "farm_group", "cycle_name", "actual_end_date", "cycle_duration",
                                    "growth", "environment", "grade_quantities", "income", "target", "target_quality_flags"],
             "group_split_column": "farm_group", "farm_group_rule": "same exact facility ID across all cycles",
             "row_aggregation_performed": False, "rows_deduplicated": False, "zero_imputation_performed": False,
             "outlier_correction_or_deletion_performed": False, "completeness_verified": False,
             "long_cycle_policy": "more than 366 days excluded for this single-season analytic cohort; not an agronomic law",
             "production_model_ready": False,
             "limitations": ["Positive recorded totals only; zero may mean unreported, so cohort is selection biased.",
                             "Facility IDs are grouping proxies, not proven unique farm-owner identities.",
                             "Actual planting day/month proxies planned planting; no archived pre-adoption plans exist.",
                             "Metadata observed for matched cycles is not proved archived before adoption.",
                             "One million kg screen is a review flag, not a validity threshold or automatic removal.",
                             "No verified cost, net income, annualization or causal adoption effect target."],
             "output_files": {}}
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, rows in {**tables, "candidates": candidates}.items():
        path = output_directory / f"strawberry_curation_{name}.csv"
        write_csv(path, rows)
        content = path.read_bytes()
        audit["output_files"][path.name] = {"sha256": digest(content), "bytes": len(content), "rows": len(rows)}
    audit_path = output_directory / "strawberry_curation_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(audit, shipping), encoding="utf-8")
    return audit


def render_report(audit: dict, rows: list[dict]) -> str:
    lines = ["# 딸기 큐레이션 실제 파일 스키마·정답 후보 검증", "",
             f"검사 기준일: {audit['as_of_date']}. ZIP SHA256: `{audit['source']['zip_sha256']}`.", "",
             "공식 정의서의 **한 작기 총출하수량 kg**는 이 큐레이션 출하 파일에만 적용한다. "
             "API 출하 행을 합산하거나 기존 API·ADP의 기간 정의를 바꾸지 않았다.", "",
             "| 표 | 원행 | 시설 ID |", "|---|---:|---:|"]
    for name, info in audit["tables"].items():
        lines.append(f"| {name} | {info['rows']:,} | {info['facilities']:,} |")
    lines += ["", f"양수 원행 {audit['shipping_positive_rows']}개 중 유일하고 날짜가 유효한 정답 후보는 "
              f"{audit['target_candidate_rows']}행·{audit['target_candidate_facilities']}시설이다. "
              f"API 시설·정식시작·종료·품목을 정확히 유일 매칭하고 catalog와 면적·품종을 확인한 후보는 "
              f"{audit['metadata_candidate_rows']}행·{audit['metadata_candidate_facilities']}시설이다.", "",
              "## 원행 보존과 제외", "",
              "출하·생육·환경 모든 원행, ZIP/XLSX 해시, 시트, 엑셀 행번호, 원값 JSON을 보존했다. "
              "중복은 합치거나 대표행을 고르지 않고 정답 후보에서 전체 제외했다. "
              "0은 실제 무출하와 미조사를 구분할 수 없어 정답으로 사용하지 않았다. "
              "작기 366일 초과 제외는 이 분석의 단일 작기 코호트 정책이며 농업 법칙이 아니다.", ""]
    for reason, count in audit["exclusion_counts"].items():
        lines.append(f"- `{reason}`: {count}행")
    lines += ["", "## API 메타데이터 결합", "",
              "시설 ID만으로 결합하지 않는다. 시설 ID·정식시작일·종료일·품목이 모두 일치하는 API 작기가 "
              "정확히 하나이고 해당 작기 catalog도 하나인 경우에만 면적을 검토했다. "
              "API 작기와 catalog의 품종·품목·면적 일치 및 양수 면적을 확인한 행만 `area_m2` 등을 채웠다. "
              "미매칭·복수매칭·면적 충돌은 추정 보정하지 않는다. 매칭 source_record_id와 원문 면적을 함께 보존했다.", ""]
    for status, count in audit["positive_metadata_match_counts"].items():
        lines.append(f"- 양수 원행 `{status}`: {count}행")
    lines += ["", "## 도입 전 입력과 검증 범위", "",
              "허용 입력 후보: " + ", ".join(f"`{name}`" for name in FEATURE_COLUMNS) + ".", "",
              "같은 시설의 여러 작기는 항상 동일 `farm_group`으로 묶는다. 실제 종료일·재배기간·시설ID·작기명·"
              "생육·환경·등급별 수량·수익금액·정답 품질 플래그는 입력에서 제외한다. "
              "실제 정식일이 계획 정식일의 대리값이며 과거 시점에 기록된 계획은 없다는 한계가 있다. "
              "작기 종료일이 지났다는 사실은 수집·검수 완료 증명이 아니다. 타깃은 **기록된 작기 총 출하량**이며 "
              "검증된 전체 수확량·연간 수확량·이익이 아니다. 학습 전 원행 단위 검토와 농가 분리 평가가 필요하다.", "",
              "## 원값 검토 항목", ""]
    for row in rows:
        if "million_kg" in row["quality_flags"]:
            lines.append(f"- `{row['source_record_id']}` / `{row['시설ID']}` / `{row['작기명']}`: "
                         f"총출하수량 {row['총출하수량']:,}kg, API 면적 {row.get('area_m2')}㎡. "
                         "백만 kg 이상이라는 보고용 플래그만 부여했고 ÷1,000 등 교정·삭제하지 않았다. "
                         "모델 결과는 이 행 포함 원값 평가와 명시적 보류 민감도 평가를 구분해야 한다.")
    lines += ["", "수익금액은 회계 정의가 확정되지 않아 매출·순이익으로 재명명하지 않았다. "
              "면적/지역은 이 ZIP에는 없고 엄격하게 일치한 별도 API에서 온 값이다. "
              "완료 검수 상태·운영비·투자비는 이 자료로 확인할 수 없다.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=SOURCE / "Strawberry_Growth_Env_Shipping_Dataset.zip")
    parser.add_argument("--acquisition", type=Path, default=SOURCE / "strawberry_acquisition.json")
    parser.add_argument("--api-directory", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--output-directory", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--report", type=Path, default=ROOT / "reports/strawberry_curation_schema_audit.md")
    args = parser.parse_args(argv)
    audit = prepare(args.zip, args.acquisition, args.api_directory, args.output_directory, args.as_of, args.report)
    print(json.dumps({key: audit[key] for key in ("target_candidate_rows", "target_candidate_facilities",
                                                "metadata_candidate_rows", "metadata_candidate_facilities")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
