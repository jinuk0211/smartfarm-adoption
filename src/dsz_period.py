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
