"""Reproduce which collected records actually describe the same farm/cycle."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


def _number(value: str | None) -> Decimal | None:
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def audit_api_links(
    cycles: list[dict[str, str]],
    output: list[dict[str, str]],
    costs: list[dict[str, str]],
) -> dict[str, Any]:
    """Count keys before joining; never multiply output rows by cost rows.

    Production/cost responses do not carry a native cycle year. A facility and
    cycle number must resolve to exactly one year and one cycle description.
    Previously computed audit columns cannot resolve an ambiguous source key.
    """
    index: dict[tuple[str, str], dict[tuple[str, ...], dict[str, str]]] = defaultdict(dict)
    identity_fields = (
        "fcltyYear", "fixplntngDe", "crpsnEndDe", "itemCodeNm", "ctvtAr"
    )
    for row in cycles:
        pair = (row.get("fcltyId", "").strip(), row.get("crpsnSn", "").strip())
        if all(pair):
            identity = tuple(row.get(field, "").strip() for field in identity_fields)
            index[pair][identity] = row

    grouped: dict[str, dict[tuple[str, str, str], list[dict[str, str]]]] = {}
    rejected: dict[str, dict[str, int]] = {}
    for label, records in (("output", output), ("cost", costs)):
        groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        reasons: Counter[str] = Counter()
        for row in records:
            pair = (row.get("fcltyId", "").strip(), row.get("crpsnSn", "").strip())
            candidates = index.get(pair, {})
            if not all(pair):
                reasons["missing_facility_or_cycle"] += 1
            elif not candidates:
                reasons["cycle_not_found"] += 1
            elif len(candidates) != 1:
                reasons["ambiguous_cycle_year_or_metadata"] += 1
            else:
                cycle = next(iter(candidates.values()))
                year = cycle.get("fcltyYear", "").strip()
                audit_year = row.get("audit_fcltyYear", "").strip()
                if not year:
                    reasons["missing_cycle_year"] += 1
                elif audit_year and audit_year != year:
                    reasons["conflicting_audit_year"] += 1
                else:
                    groups[(*pair, year)].append(row)
        grouped[label] = groups
        rejected[label] = dict(sorted(reasons.items()))

    output_keys, cost_keys = set(grouped["output"]), set(grouped["cost"])
    evidence = []
    for key in sorted(output_keys | cost_keys):
        cycle = next(iter(index[key[:2]].values()))
        output_rows = grouped["output"].get(key, [])
        cost_rows = grouped["cost"].get(key, [])
        evidence.append({
            "facility_id": key[0], "cycle_number": key[1], "cycle_year": key[2],
            "crop": cycle.get("itemCodeNm", ""),
            "cycle_start": cycle.get("fixplntngDe", ""),
            "cycle_end": cycle.get("crpsnEndDe", ""),
            "output_rows": len(output_rows), "cost_rows": len(cost_rows),
            "has_both_record_types": bool(output_rows and cost_rows),
            "cost_record_status": "observed_scope_unknown" if cost_rows else "not_observed",
            "verified_total_operating_cost_krw": None,
            "verified_income_krw": None,
            "output_source_record_ids": [r.get("source_record_id", "") for r in output_rows],
            "cost_source_record_ids": [r.get("source_record_id", "") for r in cost_rows],
        })
    overlaps = [row for row in evidence if row["has_both_record_types"]]
    return {
        "join_key": ["fcltyId", "crpsnSn", "fcltyYear"],
        "join_method": "Resolve unique cycle/year first, then compare grouped keys; no raw row join.",
        "counts": {
            "cycle_rows": len(cycles), "output_rows": len(output), "cost_rows": len(costs),
            "output_cycles": len(output_keys), "cost_cycles": len(cost_keys),
            "overlap_cycles": len(overlaps),
            "overlap_facilities": len({row["facility_id"] for row in overlaps}),
            "overlap_by_crop": dict(sorted(Counter(row["crop"] for row in overlaps).items())),
            "strawberry_overlap_cycles": sum(row["crop"] == "딸기" for row in overlaps),
            "output_cycles_without_cost": len(output_keys - cost_keys),
            "verified_complete_cost_cycles": 0,
        },
        "rejected_rows": rejected,
        "cycle_evidence": evidence,
        "complete_cost_verified": False,
        "target_farm_roi_validated": False,
        "limits": [
            "비용 기록 존재는 전체 운영비 수집 완료를 뜻하지 않습니다.",
            "ctOpcWkCost와 fmwWkCost의 중복·포괄 범위 및 조사 대상 기간이 미확인입니다.",
            "비용 기록이 없는 작기의 비용과 소득은 0원이 아닌 미확인(null)입니다.",
            "API 기록의 비용 합산값이나 단일 행을 완결 작기 비용으로 사용하지 않습니다.",
        ],
    }


def audit_public_cases(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Select published within-case accounts only after recomputing identities."""
    accepted, excluded = [], []
    ids = Counter(row.get("case_id", "") for row in rows)
    for row in rows:
        reasons = []
        if not row.get("case_id") or ids[row["case_id"]] != 1:
            reasons.append("missing_or_duplicate_case_id")
        source_url = urlparse(row.get("source_url", ""))
        if source_url.scheme not in {"https", "http"} or not source_url.netloc:
            reasons.append("missing_or_invalid_source_url")
        if not row.get("source_pdf_pages", "").strip():
            reasons.append("missing_source_pages")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", row.get("source_sha256", "")):
            reasons.append("missing_or_invalid_source_hash")
        for prefix in ("pilot", "nearby"):
            fields = (
                f"{prefix}_gross_revenue_1000krw_per_10a",
                f"{prefix}_operating_cost_1000krw_per_10a",
                f"{prefix}_reported_income_1000krw_per_10a",
            )
            values = [_number(row.get(field)) for field in fields]
            if any(value is None for value in values):
                reasons.append(f"{prefix}_missing_or_invalid_account_value")
            elif values[0] < 0 or values[1] < 0:
                reasons.append(f"{prefix}_negative_revenue_or_cost")
            elif values[0] - values[1] != values[2]:
                reasons.append(f"{prefix}_income_identity_mismatch")
        area = _number(row.get("pilot_area_m2"))
        if area is None or area <= 0:
            reasons.append("missing_or_invalid_area")
        area_ha = _number(row.get("pilot_area_ha"))
        if area_ha is not None and (area_ha <= 0 or area is None or area_ha * 10000 != area):
            reasons.append("area_ha_m2_mismatch")
        common = {
            "case_id": row.get("case_id", ""), "city": row.get("city", ""),
            "crop": row.get("crop_income_table", ""),
            "source_url": row.get("source_url", ""),
            "source_pdf_pages": row.get("source_pdf_pages", ""),
            "source_printed_pages": row.get("source_printed_pages", ""),
            "source_income_row": row.get("source_income_row", ""),
            "source_sha256": row.get("source_sha256", ""),
        }
        if reasons:
            excluded.append({**common, "reasons": reasons, "source_values": row})
            continue
        accepted.append({
            **common,
            "report_year": row.get("report_year", ""),
            "area_m2": float(area),
            "house_type": row.get("house_type", ""),
            "intervention": row.get("intervention", ""),
            "revenue_krw_per_1000m2": float(_number(row["pilot_gross_revenue_1000krw_per_10a"]) * 1000),
            "operating_cost_krw_per_1000m2": float(_number(row["pilot_operating_cost_1000krw_per_10a"]) * 1000),
            "income_krw_per_1000m2": float(_number(row["pilot_reported_income_1000krw_per_10a"]) * 1000),
            "income_identity_valid": True,
            "identity_scope": "published_case_within_one_report",
            "api_facility_id": None,
            "quantity_as_published": row.get("pilot_quantity_per_10a", ""),
            "quantity_unit_as_published": row.get("quantity_unit_as_published", ""),
            "crop_cycle_start": row.get("crop_cycle_start") or None,
            "crop_cycle_end": row.get("crop_cycle_end") or None,
            "project_budget_krw": float(_number(row["project_budget_krw"])) if _number(row.get("project_budget_krw")) is not None else None,
            "budget_scope": row.get("budget_scope", ""),
            "farm_total_capex_krw": None,
            "training_eligible": False,
            "annual_roi_validation_eligible": False,
            "reuse_license_status": row.get("reuse_license_status", ""),
        })
    return {
        "source_rows": len(rows), "accepted_cases": accepted, "excluded_cases": excluded,
        "strawberry_cases": [row for row in accepted if row["crop"] == "딸기"],
        "kg_training_eligible": False, "annual_roi_validation_eligible": False,
        "limits": [
            "동일 보고서의 사례별 시설·조수입·경영비·소득 연결이며 API 농가와의 연결이 아닙니다.",
            "산술 일치는 보고된 소득의 검산이며 비용 항목 전수 수집이나 인과효과 검증이 아닙니다.",
            "수량 머리글은 kg·주·본·단 혼합이고 행별 단위가 미확인이라 kg 모델에 넣지 않습니다.",
            "작기 기간이 없으므로 연간 소득 또는 연간 투자 회수 검증에 사용하지 않습니다.",
            "시범 사업비 2천만원은 전체 시설 투자비가 아닙니다.",
        ],
    }


def load_farm_evidence(project: Path) -> dict[str, Any]:
    """Read current local source CSVs and return reproducible evidence and hashes."""
    records, inputs = {}, []
    for label, filename in (
        ("cycles", "smartfarm_api_cycles.csv"),
        ("output", "smartfarm_api_output.csv"),
        ("cost", "smartfarm_api_cost.csv"),
        ("cases", "public_farm_gg2023_cases.csv"),
    ):
        relative = Path("data/processed") / filename
        path = project / relative
        payload = path.read_bytes()
        records[label] = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        inputs.append({
            "path": relative.as_posix(), "sha256": hashlib.sha256(payload).hexdigest(),
            "rows": len(records[label]),
        })
    return {
        "schema_version": 1, "input_files": inputs,
        "api": audit_api_links(records["cycles"], records["output"], records["cost"]),
        "public_cases": audit_public_cases(records["cases"]),
        "limits": [
            "대상 농가의 개별 비용·투자비를 확보하거나 검증한 결과가 아닙니다.",
            "공개 사례를 기존 딸기 예측 모델의 독립 검증 농가로 합치지 않습니다.",
        ],
    }
