"""Collect KMA's public 1991-2020 monthly normals and station metadata.

The POST is the anonymous public table's own form action, not a key-protected
API. Station IDs join two official sources; no farm/province mapping is made.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import openpyxl
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/climate_normals"
OUT = ROOT / "data/processed"
BASE = "https://data.kma.go.kr"
PARAMETERS = {
    "DEPTH1": "TBL_KOR_1991_30", "DEPTH2": "MNH",
    "schElmId": "AVG_TA,MAX_TA,MIN_TA,SUM_RN", "schStnId": "", "startMonth": "1",
    "selectElmType": "2", "selectElmCount": "99", "selectStnType": "2",
    "selectStnCount": "99", "difStnCount": "1", "stnFileNm": "Average30Years4.json",
}
ELEMENTS = {
    "avgTa": "mean_temperature_c", "maxTa": "mean_max_temperature_c",
    "minTa": "mean_min_temperature_c", "sumRn": "monthly_precipitation_mm",
}


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_source(name: str, payload: bytes) -> None:
    """Reject successful-HTTP error bodies before caching or replacing a source."""
    if name == "monthly_1991_2020.json":
        content = json.loads(payload)
        if not isinstance(content, dict) or content.get("code") != "00" or not isinstance(content.get("dataList"), list) or not content["dataList"]:
            raise ValueError("Monthly response lacks successful records")
        keys = set()
        months = {}
        for row in content["dataList"]:
            if not isinstance(row, dict):
                raise ValueError("Monthly record is not an object")
            station, month = row.get("stnId"), row.get("mnh")
            if type(station) is not int or type(month) is not int or month not in range(1, 13) or row.get("stYear") != 2021:
                raise ValueError("Unexpected station, integer month, or period code")
            if not isinstance(row.get("stnNm"), str) or not row["stnNm"]:
                raise ValueError("Missing station name")
            if (station, month) in keys:
                raise ValueError("Duplicate station-month record")
            keys.add((station, month))
            months.setdefault(station, set()).add(month)
            values = {key: number(row.get(key)) for key in ELEMENTS}
            if any(value is None for value in values.values()):
                raise ValueError("Missing requested climate value")
            if not values["minTa"] <= values["avgTa"] <= values["maxTa"] or values["sumRn"] < 0:
                raise ValueError("Invalid climate value order/range")
        if any(value != set(range(1, 13)) for value in months.values()):
            raise ValueError("Incomplete 12-month station record")
    elif name == "normals_point.xlsx":
        workbook = openpyxl.load_workbook(BytesIO(payload), read_only=True, data_only=True)
        try:
            rows = list(workbook.active.values)
            if len(rows) < 5 or rows[2][1:3] != ("지점번호", "지점명"):
                raise ValueError("Unexpected station spreadsheet header")
            identifiers = []
            for row in rows[4:]:
                if type(row[1]) is not int:
                    raise ValueError("Invalid station ID")
                identifiers.append(row[1])
                coordinate(row[4])
                coordinate(row[5])
                for value in row[6:11]:
                    number(value)
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate station IDs")
        finally:
            workbook.close()
    elif name.endswith(".json"):
        json.loads(payload)


def acquire(name: str, path: str, manifest: list[dict], parameters: dict | None = None) -> dict:
    url = BASE + path
    output = RAW / name
    relative = output.relative_to(ROOT).as_posix()
    method = "POST" if parameters else "GET"
    for meta in manifest:
        if (meta["source_file"] == relative and meta["source_url"] == url
                and meta.get("method", "GET") == method and meta.get("parameters") == parameters
                and output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() == meta["sha256"]):
            try:
                validate_source(name, output.read_bytes())
            except (ValueError, TypeError, zipfile.BadZipFile):
                break  # Invalid cached source: make one fresh public request.
            return meta
    response = requests.request(method, url, data=parameters, timeout=45)
    response.raise_for_status()
    if response.url != url:
        raise ValueError(f"Unexpected redirect: {path}")
    validate_source(name, response.content)
    output.write_bytes(response.content)
    meta = {
        "source_url": url, "source_file": relative, "method": method,
        "parameters": parameters, "http_status": response.status_code,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest(),
    }
    manifest[:] = [old for old in manifest if old["source_file"] != relative]
    manifest.append(meta)
    save_json(RAW / "source_manifest.json", manifest)
    return meta


def number(value: object) -> float | None:
    if value is None or value in ("", "-"):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite source value: {value}")
    return result


def coordinate(value: str) -> float:
    # The official minute-rounded table includes 34 degrees 60 minutes.
    match = re.fullmatch(r"(\d+)˚(\d+)´", value)
    if not match or int(match.group(2)) > 60:
        raise ValueError(f"Unrecognized degree/minute coordinate: {value}")
    return int(match.group(1)) + int(match.group(2)) / 60


def write_csv(name: str, rows: list[dict]) -> None:
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    sources = [
        ("info.html", "/normals/info1.do"),
        ("table.html", "/normals/table.do"),
        ("dataInfo.js", "/resources/normals/js/dataInfo.js"),
        ("30_MNH.json", "/resources/module/climate/30_MNH.json"),
        ("normals_point.xlsx", "/resources/normals/pdf_data/normals_point.xlsx"),
    ]
    by_name = {name: acquire(name, path, manifest) for name, path in sources}
    monthly_meta = acquire("monthly_1991_2020.json", "/normals/tableAjax.do", manifest, PARAMETERS)
    station_meta = by_name["normals_point.xlsx"]
    workbook = openpyxl.load_workbook(RAW / "normals_point.xlsx", read_only=True, data_only=True)
    sheet = workbook.active
    stations = []
    for row_number, row in enumerate(sheet.values, 1):
        if row_number <= 4:
            continue
        if not isinstance(row[1], int):
            raise ValueError(f"Unexpected station row at Excel row {row_number}")
        stations.append({
            "station_id": row[1], "station_name": row[2], "station_name_english": row[3],
            "latitude_degrees_minutes_original": row[4], "longitude_degrees_minutes_original": row[5],
            "latitude_degrees": coordinate(row[4]), "longitude_degrees": coordinate(row[5]),
            "elevation_m": number(row[6]), "barometer_elevation_m": number(row[7]),
            "thermometer_height_m": number(row[8]), "anemometer_height_m": number(row[9]),
            "rain_gauge_height_m": number(row[10]), "coordinate_precision": "one_arcminute_in_source",
            "normal_period_start": 1991, "normal_period_end": 2020,
            "source_url": station_meta["source_url"], "source_file": station_meta["source_file"],
            "source_sha256": station_meta["sha256"], "source_sheet": sheet.title,
            "source_excel_row": row_number,
        })
    workbook.close()
    station_map = {row["station_id"]: row for row in stations}
    if len(station_map) != len(stations):
        raise ValueError("Duplicate station IDs in the official station table")
    payload = json.loads((RAW / "monthly_1991_2020.json").read_text(encoding="utf-8"))
    if payload.get("code") != "00" or not payload.get("dataList"):
        raise ValueError("Public monthly table did not return successful records")
    monthly = []
    for index, record in enumerate(payload["dataList"]):
        station = station_map[record["stnId"]]
        if record["stYear"] != 2021 or type(record["mnh"]) is not int or record["mnh"] not in range(1, 13):
            raise ValueError("Unexpected source period code or month")
        values = {name: number(record.get(key)) for key, name in ELEMENTS.items()}
        if any(value is None for value in values.values()):
            raise ValueError(f"Missing requested normal: station {record['stnId']}, month {record['mnh']}")
        if not values["mean_min_temperature_c"] <= values["mean_temperature_c"] <= values["mean_max_temperature_c"]:
            raise ValueError("Temperature order violation")
        if values["monthly_precipitation_mm"] < 0:
            raise ValueError("Negative precipitation")
        monthly.append({
            "station_id": record["stnId"], "station_name": record["stnNm"], "month": record["mnh"],
            "station_metadata_name": station["station_name"],
            "station_name_matches_metadata": station["station_name"] == record["stnNm"],
            "normal_period_start": 1991, "normal_period_end": 2020, "source_period_code": record["stYear"],
            **values, "latitude_degrees": station["latitude_degrees"],
            "longitude_degrees": station["longitude_degrees"], "elevation_m": station["elevation_m"],
            "source_url": monthly_meta["source_url"], "source_file": monthly_meta["source_file"],
            "source_sha256": monthly_meta["sha256"], "source_json_pointer": f"/dataList/{index}",
            "station_source_file": station_meta["source_file"], "station_source_excel_row": station["source_excel_row"],
        })
    keys = [(row["station_id"], row["month"]) for row in monthly]
    counts = Counter(row["station_id"] for row in monthly)
    if len(keys) != len(set(keys)) or set(counts) != set(station_map) or set(counts.values()) != {12}:
        raise ValueError("Monthly station coverage/uniqueness failed")
    write_csv("climate_normals_stations.csv", stations)
    write_csv("climate_normals_monthly.csv", monthly)
    validation = {
        "station_rows": len(stations), "monthly_rows": len(monthly), "months_per_station": 12,
        "duplicate_keys": 0, "missing_requested_values": 0,
        "station_name_variants": [dict(station_id=sid, monthly_name=name, metadata_name=meta_name)
                                  for sid, name, meta_name in sorted({
                                      (r["station_id"], r["station_name"], r["station_metadata_name"])
                                      for r in monthly if not r["station_name_matches_metadata"]})],
        "temperature_order_valid": True, "precipitation_nonnegative": True,
        "normal_period": [1991, 2020], "farm_or_province_station_mapping_created": False,
        "source_coordinates": "Minute-rounded degrees; source 34 degrees 60 minutes is numerically normalized to 35.",
        "period_limitation": "At least 10 years observed within the 1991-2020 window; not every station has 30 complete years.",
        "model_limitation": "Do not treat these published normals as available in 2020-era historical backtests.",
    }
    save_json(RAW / "extraction_validation.json", validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
