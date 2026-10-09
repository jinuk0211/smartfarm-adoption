"""Verify and audit one explicit API run without aggregating farm quantities or costs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

if __package__:
    from .collect_smartfarm_api import BASE_URL, OPERATIONS, CollectionError, response_records
else:
    from collect_smartfarm_api import BASE_URL, OPERATIONS, CollectionError, response_records


ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "getFcltyInfoDataList": "catalog",
    "getFcltyDateInfoData": "cycles",
    "getMngtOutputDataList": "output",
    "getMngtCostDataList": "cost",
}
MANAGEMENT = {"output": "getMngtOutputDataList", "cost": "getMngtCostDataList"}


class PreparationError(Exception):
    """A source-integrity problem; do not create normalized output."""


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def identity(row: dict, include_year: bool = False) -> tuple[str, ...] | None:
    fields = ("fcltyId", "crpsnSn", "fcltyYear") if include_year else ("fcltyId", "crpsnSn")
    if any(row.get(name) is None or str(row[name]).strip() == "" for name in fields):
        return None
    return tuple(str(row[name]) for name in fields)


def iso_date(value) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def request_date(value) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date() if isinstance(value, str) and len(value) == 8 else None
    except ValueError:
        return None


def area_status(value) -> str:
    if value is None or value == "":
        return "missing"
    try:
        number = float(value)
    except (ValueError, TypeError):
        return "invalid"
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        return "invalid"
    return "positive" if number > 0 else "zero"


def load_run(manifest_path: Path):
    """Read one manifest snapshot, verifying every saved response and record file."""
    manifest_path = manifest_path.resolve()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("endpoint_base") != BASE_URL or not isinstance(manifest.get("requests"), list):
        raise PreparationError("Unsupported source manifest.")
    tables = {name: [] for name in TABLES.values()}
    requests = []
    for number, entry in enumerate(manifest["requests"], 1):
        operation, params = entry.get("source_operation"), entry.get("parameters")
        if operation not in OPERATIONS or not isinstance(params, dict) or set(params) != set(OPERATIONS[operation]):
            raise PreparationError("Invalid operation or parameters in source manifest.")
        request = {"source_request_number": number, "source_operation": operation,
                   "source_parameters_json": canonical(params), "source_status": entry.get("status"),
                   "source_record_count": entry.get("record_count"), "source_no_data": entry.get("no_data", False),
                   "source_response_sha256": entry.get("response_sha256"),
                   "source_records_sha256": entry.get("records_sha256"), "source_parameters": params}
        requests.append(request)
        if entry.get("status") != "saved":
            continue
        contents = {}
        for kind in ("response", "records"):
            filename = entry.get(f"{kind}_file")
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise PreparationError("Unsafe file reference in source manifest.")
            path = (manifest_path.parent / filename).resolve()
            if path.parent != manifest_path.parent:
                raise PreparationError("Source file must remain in the selected run directory.")
            contents[kind] = path.read_bytes()
            if sha256(contents[kind]) != entry.get(f"{kind}_sha256"):
                raise PreparationError("Source response or records SHA256 mismatch.")
        payload = json.loads(contents["response"])
        records, no_data = response_records(payload, operation)
        stored = [json.loads(line) for line in contents["records"].decode("utf-8").splitlines()]
        if (records != stored or type(entry.get("record_count")) is not int
                or entry["record_count"] != len(records) or request["source_no_data"] is not no_data):
            raise PreparationError("Response, records, row count or no-data metadata disagree.")
        if no_data and contents["records"] != b"":
            raise PreparationError("No-data response must have an empty records file.")
        request["audit_request_result"] = "no_data" if no_data else "records" if records else "empty_success"
        if operation not in TABLES:
            continue
        for row_number, raw in enumerate(records, 1):
            if any(name.startswith(("source_", "audit_")) for name in raw):
                raise PreparationError("Source fields conflict with normalization metadata names.")
            tables[TABLES[operation]].append({
                **raw, "source_record_id": f"{manifest_path.parent.name}:{number}:{row_number}",
                "source_request_number": number, "source_row_number": row_number,
                "source_operation": operation, "source_raw_record_json": canonical(raw),
                "source_response_sha256": entry["response_sha256"],
                "source_records_sha256": entry["records_sha256"],
                "source_original_retrieved_at_utc": entry.get("original_retrieved_at_utc", entry.get("retrieved_at_utc")),
                "audit_flags": [],
            })
    return manifest, manifest_bytes, tables, requests


def audit_tables(manifest: dict, tables: dict, requests: list[dict]) -> dict:
    """Annotate joins and record quality, leaving every business value unchanged."""
    request_by_number = {r["source_request_number"]: r for r in requests}
    catalog_index, cycle_index = defaultdict(list), defaultdict(list)
    for row in tables["catalog"]:
        catalog_index[identity(row, True)].append(row)
    for row in tables["cycles"]:
        cycle_index[identity(row)].append(row)

    def check_crop(row, other):
        for field in ("itemCode", "itemCodeNm"):
            if row.get(field) is not None and other.get(field) is not None and str(row[field]) != str(other[field]):
                row["audit_flags"].append("crop_mismatch")
                break

    for table, rows in tables.items():
        duplicates = Counter(row["source_raw_record_json"] for row in rows)
        date_field = {"output": "opShipDe", "cost": "ctPayDe"}.get(table)
        same_day = Counter((identity(row), row.get(date_field)) for row in rows
                           if date_field and identity(row) and iso_date(row.get(date_field)))
        for row in rows:
            flags = row["audit_flags"]
            request = request_by_number[row["source_request_number"]]
            params = request["source_parameters"]
            row["audit_exact_duplicate_count"] = duplicates[row["source_raw_record_json"]]
            if row["audit_exact_duplicate_count"] > 1:
                flags.append("exact_duplicate")
            if identity(row, table in {"catalog", "cycles"}) is None:
                flags.append("missing_identity")
            for field in ("fcltyId", "crpsnSn", "fcltyYear"):
                if field in params and str(row.get(field)) != str(params[field]):
                    flags.append("request_identity_mismatch")
                    break
            if table in {"catalog", "cycles"}:
                row["audit_area_status"] = area_status(row.get("ctvtAr"))
                if row["audit_area_status"] != "positive":
                    flags.append("area_" + row["audit_area_status"])
            if table == "catalog":
                if len(catalog_index[identity(row, True)]) > 1:
                    flags.append("duplicate_catalog_key")
                continue
            if table == "cycles":
                candidates = catalog_index.get(identity(row, True), []) if identity(row, True) else []
                row["audit_catalog_join_status"] = "matched" if len(candidates) == 1 else "missing" if not candidates else "ambiguous"
                if len(candidates) == 1:
                    row["audit_catalog_source_record_id"] = candidates[0]["source_record_id"]
                    check_crop(row, candidates[0])
                    if row.get("ctvtAr") != candidates[0].get("ctvtAr"):
                        flags.append("catalog_cycle_area_mismatch")
                else:
                    flags.append("catalog_join_" + row["audit_catalog_join_status"])
                if len(cycle_index[identity(row)]) > 1:
                    flags.append("ambiguous_facility_cycle_key")
                start = iso_date(row.get("fixplntngDe", row.get("fixPlntngDe")))
                end = iso_date(row.get("crpsnEndDe"))
                if not start or not end or end < start:
                    flags.append("invalid_cycle_dates")
                continue
            candidates = cycle_index.get(identity(row), []) if identity(row) else []
            row["audit_cycle_join_status"] = "matched" if len(candidates) == 1 else "missing" if not candidates else "ambiguous"
            observed_date = iso_date(row.get(date_field))
            if not observed_date:
                flags.append("missing_or_invalid_record_date")
            req_start, req_end = request_date(params.get("fixPlntngDe")), request_date(params.get("crpsnEndDe"))
            if not req_start or not req_end or req_end < req_start:
                flags.append("invalid_request_dates")
            elif observed_date and not req_start <= observed_date <= req_end:
                flags.append("outside_request_period")
            row["audit_same_day_record_count"] = same_day.get((identity(row), row.get(date_field)), 0)
            if row["audit_same_day_record_count"] > 1:
                flags.append("multiple_records_same_day")
            if len(candidates) != 1:
                flags.append("cycle_join_" + row["audit_cycle_join_status"])
                continue
            cycle = candidates[0]
            row.update({"audit_cycle_source_record_id": cycle["source_record_id"],
                        "audit_fcltyYear": cycle.get("fcltyYear"), "audit_itemCodeNm": cycle.get("itemCodeNm"),
                        "audit_cycle_quality_flags": sorted(set(cycle["audit_flags"])),
                        "audit_cycle_area_m2": cycle.get("ctvtAr"), "audit_area_status": area_status(cycle.get("ctvtAr"))})
            if row["audit_area_status"] != "positive":
                flags.append("area_" + row["audit_area_status"])
            check_crop(row, cycle)
            start = iso_date(cycle.get("fixplntngDe", cycle.get("fixPlntngDe")))
            end = iso_date(cycle.get("crpsnEndDe"))
            if not start or not end or end < start:
                flags.append("invalid_cycle_dates")
            elif observed_date and not start <= observed_date <= end:
                flags.append("outside_cycle_period")

    note_keywords = ("작기", "전체", "총수확량", "연간", "기간", "누적")
    for row in tables["output"]:
        note = row.get("opNote")
        row["audit_note_period_keywords"] = [word for word in note_keywords if isinstance(note, str) and word in note]

    selection = manifest.get("selection", {})

    def selected(row):
        return all(not selection.get(option) or str(row.get(field)) in [str(x) for x in selection[option]]
                   for option, field in (("facility", "fcltyId"), ("year", "fcltyYear"), ("crop", "itemCodeNm")))

    expected_pairs = {(str(row.get("fcltyId")), str(row.get("fcltyYear")))
                      for row in tables["catalog"] if selected(row) and identity(row, True)}
    expected_catalog_cycles = {identity(row, True) for row in tables["catalog"] if selected(row) and identity(row, True)}
    returned_cycles = {identity(row, True) for row in tables["cycles"] if selected(row) and identity(row, True)}
    observed_pairs = {(str(r["source_parameters"]["fcltyId"]), str(r["source_parameters"]["fcltyYear"]))
                      for r in requests if r["source_operation"] == "getFcltyDateInfoData" and r["source_status"] == "saved"}
    request_index = defaultdict(list)
    for request in requests:
        request_index[(request["source_operation"], canonical(request["source_parameters"]))].append(request)
    expected_management = set()
    for cycle in tables["cycles"]:
        start = iso_date(cycle.get("fixplntngDe", cycle.get("fixPlntngDe")))
        end = iso_date(cycle.get("crpsnEndDe"))
        active = selected(cycle) and identity(cycle, True) and start and end and end >= start
        if active and selection.get("start"):
            bound = iso_date(selection["start"])
            if not bound:
                raise PreparationError("Invalid source selection start date.")
            start = max(start, bound)
        if active and selection.get("end"):
            bound = iso_date(selection["end"])
            if not bound:
                raise PreparationError("Invalid source selection end date.")
            end = min(end, bound)
        active = active and start <= end
        for table, operation in MANAGEMENT.items():
            result = "outside_selection_or_invalid_cycle"
            if active:
                params = {"fcltyId": str(cycle["fcltyId"]), "crpsnSn": cycle["crpsnSn"],
                          "fixPlntngDe": start.strftime("%Y%m%d"), "crpsnEndDe": end.strftime("%Y%m%d")}
                signature = (operation, canonical(params))
                expected_management.add(signature)
                matches = request_index.get(signature, [])
                result = "not_requested" if not matches else "ambiguous_requests" if len(matches) > 1 else matches[0].get("audit_request_result", matches[0]["source_status"])
            cycle[f"audit_{table}_request_status"] = result
    successful_management = {(r["source_operation"], canonical(r["source_parameters"])) for r in requests
                             if r["source_operation"] in MANAGEMENT.values() and r["source_status"] == "saved"}
    missing_pairs = expected_pairs - observed_pairs
    missing_management = expected_management - successful_management
    coverage = manifest.get("coverage", {})
    catalog_requests = [r for r in requests if r["source_operation"] == "getFcltyInfoDataList"]
    complete = (manifest.get("status") == "completed" and bool(manifest.get("completed_at_utc"))
                and len(catalog_requests) == 1 and catalog_requests[0]["source_status"] == "saved"
                and all(r["source_status"] == "saved" for r in requests)
                and not missing_pairs and not missing_management and not manifest.get("skipped_cycles")
                and not coverage.get("limit_reasons") and not manifest.get("limit_reasons"))
    for rows in tables.values():
        for row in rows:
            row["audit_flags"] = sorted(set(row["audit_flags"]))
            row["audit_training_eligible"] = False
    return {
        "request_scope_complete": bool(complete), "source_status": manifest.get("status"),
        "selection": selection, "source_coverage": coverage,
        "expected_facility_year_count": len(expected_pairs), "saved_facility_year_count": len(observed_pairs),
        "expected_catalog_cycle_count": len(expected_catalog_cycles), "returned_selected_cycle_count": len(returned_cycles),
        "missing_catalog_cycle_count": len(expected_catalog_cycles - returned_cycles),
        "unexpected_returned_cycle_count": len(returned_cycles - expected_catalog_cycles),
        "catalog_cycle_coverage_complete": not (expected_catalog_cycles - returned_cycles),
        "missing_facility_year_count": len(missing_pairs), "expected_management_request_count": len(expected_management),
        "unexpected_saved_facility_year_count": len(observed_pairs - expected_pairs),
        "missing_management_request_count": len(missing_management),
        "no_data_requests_by_operation": dict(Counter(r["source_operation"] for r in requests if r.get("audit_request_result") == "no_data")),
        "request_status_counts": dict(Counter(r["source_status"] for r in requests)),
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "output_note_audit": {
            "nonempty_rows": sum(isinstance(row.get("opNote"), str) and bool(row["opNote"].strip()) for row in tables["output"]),
            "period_keyword_row_counts": dict(Counter(word for row in tables["output"] for word in row["audit_note_period_keywords"])),
            "interpretation": "keywords_are_not_proof_of_record_period_or_cycle_completeness",
        },
        "quality_flag_counts": {name: dict(Counter(flag for row in rows for flag in row["audit_flags"])) for name, rows in tables.items()},
        "training_eligible": False, "quantity_revenue_cost_aggregation": "not_performed",
        "cycle_completeness": "not_established_by_request_completion",
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(name for row in rows for name in row if name != "source_parameters"))
    if not fields:
        fields = ["source_record_id", "audit_training_eligible"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: canonical(value) if isinstance(value, (dict, list)) else value
                             for name, value in row.items() if name != "source_parameters"})


def prepare(manifest_path: Path, output_dir: Path) -> dict:
    manifest, manifest_bytes, tables, requests = load_run(manifest_path)
    audit = audit_tables(manifest, tables, requests)
    audit.update({"prepared_at_utc": datetime.now(timezone.utc).isoformat(),
                  "source_run_id": manifest_path.resolve().parent.name,
                  "source_manifest": str(manifest_path.resolve()), "source_manifest_sha256": sha256(manifest_bytes),
                  "source_manifest_snapshot": "smartfarm_api_source_manifest.json",
                  "record_value_preservation": "original_fields_and_canonical_raw_record_json; no_unit_conversion_or_deduplication"})
    # No output is created until all saved source files pass integrity checks.
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for table, rows in {**tables, "requests": requests}.items():
        path = output_dir / f"smartfarm_api_{table}.csv"
        write_csv(path, rows)
        paths.append(path)
    (output_dir / audit["source_manifest_snapshot"]).write_bytes(manifest_bytes)
    audit["output_files"] = {path.name: {"sha256": sha256(path.read_bytes()), "bytes": path.stat().st_size} for path in paths}
    (output_dir / "smartfarm_api_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="One explicit run manifest; no directory scanning or pilot merging")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args(argv)
    try:
        audit = prepare(args.manifest, args.output_dir)
    except (PreparationError, CollectionError, OSError, ValueError, KeyError, TypeError):
        print("Preparation stopped: source integrity, schema or manifest snapshot could not be verified; raw files were not changed.", file=sys.stderr)
        return 1
    print(json.dumps({"row_counts": audit["row_counts"], "request_scope_complete": audit["request_scope_complete"],
                      "source_status": audit["source_status"], "training_eligible": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
