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
