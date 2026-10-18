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
