"""Generate deterministic, visibly synthetic DSZ execution fixtures (not real farms)."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.dsz_data import FEATURES, load_schema  # noqa: E402


def main() -> None:
    target = Path(__file__).parent / "input"
    target.mkdir(parents=True, exist_ok=True)
    schema = load_schema()
    randomizer = random.Random(142)
    crops = ["딸기", "오이", "토마토", "방울토마토", "파프리카"]
    regions = ["경상남도 진주시", "충청남도 논산시", "전북특별자치도 김제시", "경상북도 상주시"]
    rows = {table_id: [] for table_id in schema["tables"]}

    def record(table_id, **values):
        row = {column["name"]: "" for column in schema["tables"][table_id]["columns"]}
        row.update(STR_DT="2022-08-01 10:00:00", STR_USERID="SYNTHETIC_FIXTURE")
        row.update(values)
        rows[table_id].append(row)

    for farm in range(40):
        facility = f"SYN_FARM_{farm:03d}"
        area = 600 + (farm % 8) * 150
        farm_effect = randomizer.uniform(0.72, 1.3)
        for year in [2021, 2022]:
            cycle = (year - 2021) * 40 + farm + 1
            start_month = 1 + farm % 3
            shipment = round(area * [3, 8, 7, 5, 6][farm % 5] * farm_effect * randomizer.uniform(0.8, 1.2))
            revenue = round(shipment * [5000, 1800, 2200, 4000, 3300][farm % 5] * randomizer.uniform(0.75, 1.25), 2)
            record("DZ_002", FRMTM_SNO=str(cycle), FRMTM_YR=str(year), FCLT_ID=facility,
                   ITEM_NM=crops[farm % 5], AREA_NM=regions[farm % 4],
                   SACT_INTLCK_SPR_NM="단동" if farm % 2 else "연동", HTHS_SCL_CN=f"{1 + farm % 3}개 동",
                   FRMTM_BGNG_YMD=f"{year}{start_month:02d}01", FRMTM_END_YMD=f"{year}0630", HTHS_SFC=str(area))
            record("DZ_004", EXMN_SNO=str(cycle), EXMN_YMD=f"{year}0630", FCLT_ID=facility,
                   ALL_SHPMNT_KGUNT_QTY=str(shipment), ALL_INCM_AMT=f"{revenue:.2f}")
    # A few valid records test optional table loading. They never enter FEATURES.
    record("DZ_001", FRMTM_YR="2021", FCLT_ID="SYN_FARM_000", MSRM_DT="2021-01-10 12:00:00", INR_CO2_QTY_MRCNT="510.20")
    record("DZ_003", FRMTM_YR="2021", FCLT_ID="SYN_FARM_000", EXMN_YMD="20210110", SMPL_SNO="1", GRDV_NOFWK="2", FLVS_MMUNT_MRCNT="104.00")
    record("DZ_005", FCLT_ID="SYN_FARM_000", OBSV_PNT_CDCN="001", OBSV_YMD="20210110", OBSV_PNT_NM="합성지점", TOP_TMPRT_MSRVL="18")
    record("DZ_006", FCLT_ID="SYN_FARM_000", OBSV_PNT_CDCN="001", PRSTN_DT="2021-01-10 12:00:00", OBSV_PNT_NM="합성지점", PRSTN_CN="합성 특보")
    record("DZ_007", FCLT_ID="SYN_FARM_000", OBSV_PNT_CDCN="001", TPHN_ENG_NM="SYNTHETIC", OBSV_DT="2021-01-10 12:00:00", TPHN_NM="합성태풍")
    for table_id, records in rows.items():
        pd.DataFrame(records).to_csv(target / f"{table_id}.csv", index=False, encoding="utf-8-sig")
    (target / "fixture_manifest.json").write_text(json.dumps({
        "data_kind": "synthetic_schema_fixture", "seed": 142, "facility_count": 40, "cycle_count": 80,
        "purpose": "Execution and schema-contract demonstration only. No real farm measurements or predictive accuracy.",
        "generator": "data/examples/dsz/generate_fixture.py"
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plans = pd.DataFrame([dict(zip(FEATURES, ["딸기", regions[0], "연동", "2개 동", 1000, 2023, 2]))])
    plans.to_csv(Path(__file__).parent / "example_plans.csv", index=False, encoding="utf-8-sig")
    print(f"Synthetic DSZ fixture: 40 facilities, 80 cycles -> {target}")


if __name__ == "__main__":
    main()
