"""Prepare the supplied DSZ schema; fixture data never represents real outcomes."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "config/dsz_schema.json"
FEATURES = ["crop", "region", "greenhouse_type", "greenhouse_size", "area_m2",
            "planned_start_year", "planned_start_month"]
TARGETS = {"reported_shipment_kg": "ALL_SHPMNT_KGUNT_QTY",
           "reported_revenue_krw": "ALL_INCM_AMT"}
TARGET_ASSUMPTION = "single_record_per_cycle"
MANAGEMENT_POLICIES = [TARGET_ASSUMPTION, "incremental_sum", "latest_cumulative"]
CANDIDATE_COLUMNS = ["row_id", "facility_id", "cycle_id"] + FEATURES + list(TARGETS) + [
    "shipment_eligible", "revenue_eligible", "data_kind", "target_assumption",
    "target_period_confirmed", "facility_source_file", "facility_source_row",
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


def load_tables(input_dir: Path, schema: dict, encoding: str = "utf-8-sig") -> tuple[dict, list]:
    """Select exact supplied table names or DZ_00N aliases, without column guessing."""
    aliases = {alias.upper(): table_id for table_id, table in schema["tables"].items()
               for alias in [table_id, table["filename"]]}
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
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
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
                        "rows": len(frame), "encoding": encoding if path.suffix.lower() == ".csv" else "xlsx",
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


def build_candidates(tables: dict, data_kind: str, policy: str = TARGET_ASSUMPTION) -> tuple[pd.DataFrame, pd.DataFrame]:
    if policy not in MANAGEMENT_POLICIES:
        raise ValueError(f"Unknown management policy: {policy}")
    facilities, management = tables["DZ_002"], tables["DZ_004"]
    exclusions, cycles = [], []

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
        survey = surveys[0]
        source_rows = [int(survey["_source_row"]) for survey in surveys]
        candidate = {"row_id": f"DZ002:{row['_source_row']}:DZ004:" + ",".join(map(str, source_rows)),
                     "facility_id": row["FCLT_ID"], "cycle_id": row["FRMTM_SNO"],
                     "crop": row["ITEM_NM"], "region": row["AREA_NM"],
                     "greenhouse_type": row["SACT_INTLCK_SPR_NM"], "greenhouse_size": row["HTHS_SCL_CN"],
                     "area_m2": float(Decimal(row["HTHS_SFC"])),
                     "planned_start_year": cycle["start"].year, "planned_start_month": cycle["start"].month,
                     "data_kind": data_kind, "target_assumption": policy,
                     "target_period_confirmed": False,
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
            candidate[f"{prefix}_eligible"] = value is not None and value >= 0
            if not candidate[f"{prefix}_eligible"]:
                exclude("DZ_004", survey, f"{target}_missing_invalid_or_negative")
        candidates.append(candidate)
    return pd.DataFrame(candidates, columns=CANDIDATE_COLUMNS), pd.DataFrame(exclusions, columns=ISSUE_COLUMNS)


def prepare(input_dir: Path, output_dir: Path, *, encoding: str = "utf-8-sig",
            schema_path: Path = SCHEMA_PATH, management_policy: str = TARGET_ASSUMPTION) -> dict:
    if management_policy not in MANAGEMENT_POLICIES:
        raise ValueError(f"Unknown management policy: {management_policy}")
    schema = load_schema(schema_path)
    tables, sources = load_tables(input_dir, schema, encoding)
    data_kind = detect_data_kind(tables, input_dir)
    validation, inventory = [], {key: {"present": False, "rows": 0} for key in schema["tables"]}
    for table_id in tables:
        tables[table_id], issues = validate_table(table_id, tables[table_id], schema["tables"][table_id])
        validation.extend(issues)
        inventory[table_id] = {"present": True, "rows": len(tables[table_id]), "schema_valid_rows": int(
            tables[table_id]["_invalid_columns"].map(lambda columns: not columns).sum()),
            "model_usage": "pre_adoption_metadata" if table_id == "DZ_002" else
            "assumed_reported_targets" if table_id == "DZ_004" else "inventory_only_never_model_features"}
    candidates, exclusions = build_candidates(tables, data_kind, management_policy)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {"candidates": output_dir / "dsz_model_candidates.csv",
             "exclusions": output_dir / "dsz_exclusions.csv", "validation": output_dir / "dsz_validation.csv"}
    candidates.to_csv(paths["candidates"], index=False, encoding="utf-8-sig")
    exclusions.to_csv(paths["exclusions"], index=False, encoding="utf-8-sig")
    pd.DataFrame(validation, columns=ISSUE_COLUMNS).to_csv(paths["validation"], index=False, encoding="utf-8-sig")
    manifest = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_kind": data_kind, "input_dir": str(input_dir.resolve()),
                "schema_sha256": sha256(schema_path), "source_dictionary_sha256": schema["dictionary_sha256"],
                "target_assumption": management_policy, "target_period_confirmed": False,
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
                                "Management aggregation is an explicit operator assumption, never verified from the schema.",
                                "Start year/month represent the planned start available at prediction time.",
                                "Synthetic fixtures demonstrate execution only, never real predictive accuracy.",
                                "Private input data and predictions must stay within the approved safe-zone workflow."]}
    (output_dir / "dsz_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
