"""Audit the actual RDA 2024 archive without inventing units or cycle totals."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/adp"
OUT = ROOT / "data/processed"
EXPECTED_SHA = "0a59624ffd34f781a888c8b2c9ccd4553f57c772ddc4e5529a0588c7bcceb0ec"
KEYS = ["도", "시군", "품목", "작기", "농가명"]
TARGET_CROPS = {"딸기", "오이", "완숙토마토", "방울토마토", "파프리카"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    """Reject traversal/symlink entries before extracting the known archive."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Archive path escapes extraction directory")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Archive contains a symbolic link")
        zipped.extractall(destination)


def normalized_keys(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns={"지역(도)": "도", "도명": "도"}).copy()
    for column in KEYS:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    # XLSX uses zero-padded numeric codes; CSV uses the same unpadded codes.
    for column in ["농가명", "작기"]:
        if not frame[column].str.fullmatch(r"\d+").all():
            raise ValueError(f"Unexpected nonnumeric join field: {column}")
        frame[column] = pd.to_numeric(frame[column]).astype("int64").astype(str)
    return frame


def surrogate(values: tuple[str, ...]) -> str:
    encoded = json.dumps(values, ensure_ascii=False).encode("utf-8")
    return "ADP24_F_" + hashlib.sha256(encoded).hexdigest()[:16]


def save_csv(frame: pd.DataFrame, name: str) -> dict:
    path = OUT / name
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return {"file": str(path.relative_to(ROOT)), "rows": len(frame), "sha256": sha256(path)}


def inventory_csv(path: Path, cultivation: pd.DataFrame) -> dict:
    rows = matched = invalid_dates = 0
    missing: dict[str, int] = {}
    identities: set[tuple] = set()
    columns: list[str] = []
    earliest = latest = None
    join_lookup = cultivation[KEYS + ["cycle_id"]]
    for chunk in pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False, chunksize=50000):
        columns = list(chunk.columns)
        rows += len(chunk)
        for column in columns:
            missing[column] = missing.get(column, 0) + int(chunk[column].eq("").sum())
        normalized = normalized_keys(chunk)
        identities.update(normalized[KEYS].itertuples(index=False, name=None))
        joined = normalized[KEYS].merge(join_lookup, on=KEYS, how="left", validate="many_to_one")
        matched += int(joined["cycle_id"].notna().sum())
        date_column = next(c for c in ["출하일자", "조사일자", "측정시간"] if c in chunk)
        dates = pd.to_datetime(chunk[date_column], errors="coerce", format="mixed")
        invalid_dates += int(dates.isna().sum())
        if dates.notna().any():
            low, high = dates.min(), dates.max()
            earliest = low if earliest is None else min(earliest, low)
            latest = high if latest is None else max(latest, high)
    return {
        "file": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
        "sha256": sha256(path), "encoding": "cp949", "rows": rows,
        "columns": columns, "missing_by_column": missing,
        "distinct_source_cycle_keys": len(identities), "matched_rows": matched,
        "unmatched_rows": rows - matched, "invalid_date_rows": invalid_dates,
        "first_date": str(earliest), "last_date": str(latest),
    }


def main() -> None:
    archive = RAW / "smartfarm_2024.zip"
    if sha256(archive) != EXPECTED_SHA:
        raise ValueError("Archive differs from the inspected source version")
    safe_extract(archive, RAW / "extracted")
    folder = RAW / "extracted/2024"
    OUT.mkdir(parents=True, exist_ok=True)
    workbook = next(folder.rglob("*.xlsx"))
    source_cultivation = pd.read_excel(workbook, sheet_name="재배정보", dtype=str).fillna("")
    cultivation = normalized_keys(source_cultivation)
    if cultivation.duplicated(KEYS).any() or cultivation["연번"].duplicated().any():
        raise ValueError("Cultivation join/serial keys are not unique")
    cultivation["cycle_id"] = cultivation["연번"].map(lambda x: f"ADP24_C_{int(x):04d}")
    # Conservative validation grouping across crops/cycles, not a verified national farm ID.
    cultivation["farm_group_id"] = [surrogate((r[0], r[1], r[4])) for r in cultivation[KEYS].itertuples(index=False, name=None)]
    cultivation["planting_date"] = pd.to_datetime(cultivation["정식일"], errors="raise").dt.strftime("%Y-%m-%d")
    rename = {
        "연번": "source_serial", "연도": "source_year", "작기": "source_cycle_number",
        "도": "province", "시군": "city", "품목": "crop", "품종": "variety",
        "온실종류": "greenhouse_material", "온실유형": "greenhouse_structure",
        "전체면적": "total_area_raw", "식부면적": "planted_area_raw", "재식밀도": "planting_density_raw",
        "환경데이터": "source_has_environment", "생육데이터": "source_has_growth", "판매데이터": "source_has_sales",
    }
    cycles = cultivation.rename(columns=rename)[list(rename.values()) + ["cycle_id", "farm_group_id", "planting_date"]].copy()
    cycles["source_xlsx_row"] = range(2, len(cycles) + 2)
    for column in ["total_area_raw", "planted_area_raw", "planting_density_raw"]:
        cycles[column] = pd.to_numeric(cycles[column], errors="raise")
    cycles["area_unit_status"] = "not_specified_in_archive"
    cycles["density_unit_status"] = "not_specified_in_archive"
    cycles["target_crop"] = cycles["crop"].isin(TARGET_CROPS)

    production_path = next(folder.rglob("생산_2024.csv"))
    production = normalized_keys(pd.read_csv(production_path, encoding="cp949", dtype=str, keep_default_na=False))
    original_columns = list(production.columns)
    production["source_csv_row"] = range(2, len(production) + 2)
    production["record_id"] = production["source_csv_row"].map(lambda x: f"ADP24_P_{x:06d}")
    production["exact_duplicate_any"] = production.duplicated(original_columns, keep=False)
    production["exact_duplicate_after_first"] = production.duplicated(original_columns)
    production["multiple_records_on_same_date"] = production.duplicated(KEYS + ["출하일자"], keep=False)
    joined = production.merge(cultivation[KEYS + ["cycle_id", "farm_group_id", "planting_date"]], on=KEYS, how="left", validate="many_to_one")
    if joined["cycle_id"].isna().any():
        raise ValueError("Unmatched production records; no partial output accepted")
    records = joined.rename(columns={"품목": "crop", "출하일자": "shipment_date", "총출하량": "shipment_quantity_raw", "판매금액": "sales_amount_raw"})
    dates = pd.to_datetime(records["shipment_date"], errors="raise")
    records["shipment_date"] = dates.dt.strftime("%Y-%m-%d")
    records["before_planting"] = dates.lt(pd.to_datetime(records["planting_date"]))
    for column in ["shipment_quantity_raw", "sales_amount_raw"]:
        records[column] = pd.to_numeric(records[column].replace("", pd.NA), errors="raise")
    records["quantity_unit_status"] = "not_specified_in_archive"
    records["sales_unit_status"] = "not_specified_in_archive"
    records["record_period_status"] = "transaction_period_or_cumulative_not_defined"
    records = records[["record_id", "source_csv_row", "cycle_id", "farm_group_id", "crop", "shipment_date", "shipment_quantity_raw", "sales_amount_raw", "quantity_unit_status", "sales_unit_status", "record_period_status", "exact_duplicate_any", "exact_duplicate_after_first", "multiple_records_on_same_date", "before_planting"]]

    quality = records.groupby("cycle_id").agg(
        production_record_count=("record_id", "size"), recorded_shipment_dates=("shipment_date", "nunique"),
        first_shipment_date=("shipment_date", "min"), last_shipment_date=("shipment_date", "max"),
        duplicate_rows_any=("exact_duplicate_any", "sum"), duplicate_rows_after_first=("exact_duplicate_after_first", "sum"),
        same_date_multiple_rows=("multiple_records_on_same_date", "sum"), before_planting_rows=("before_planting", "sum"),
        missing_sales_rows=("sales_amount_raw", lambda values: int(values.isna().sum())),
        quantity_min_raw=("shipment_quantity_raw", "min"), quantity_median_raw=("shipment_quantity_raw", "median"), quantity_max_raw=("shipment_quantity_raw", "max"),
    ).reset_index()
    quality = cycles[["cycle_id", "farm_group_id", "crop", "target_crop", "source_has_sales"]].merge(quality, on="cycle_id", how="left", validate="one_to_one")
    counts = ["production_record_count", "recorded_shipment_dates", "duplicate_rows_any", "duplicate_rows_after_first", "same_date_multiple_rows", "before_planting_rows", "missing_sales_rows"]
    quality[counts] = quality[counts].fillna(0).astype(int)
    quality["sales_availability_conflict"] = quality["source_has_sales"].eq("유").ne(quality["production_record_count"].gt(0))
    quality["training_eligible_yield_kg_m2"] = False
    quality["target_readiness"] = "pending_source_definition"
    quality.loc[quality.production_record_count.eq(0), "target_readiness"] = "no_production_records"
    quality["target_definition_pending"] = "quantity_and_area_units;record_period;cycle_end_or_completeness"
    quality["quality_review_flags"] = ""
    quality.loc[quality.before_planting_rows.gt(0), "quality_review_flags"] += "production_before_planting;"
    quality.loc[quality.duplicate_rows_any.gt(0), "quality_review_flags"] += "identical_records_without_transaction_id;"
    quality.loc[quality.sales_availability_conflict, "quality_review_flags"] += "source_sales_availability_conflict;"
    quality["quality_review_flags"] = quality["quality_review_flags"].str.rstrip(";")

    inventory = [inventory_csv(path, cultivation) for path in sorted(folder.rglob("*.csv"))]
    inventory.append({"file": str(workbook.relative_to(ROOT)), "bytes": workbook.stat().st_size, "sha256": sha256(workbook), "rows": len(cultivation), "columns": list(source_cultivation.columns), "encoding": "xlsx", "sheet": "재배정보"})
    (RAW / "schema_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    products = [save_csv(cycles, "adp_cultivation_cycles.csv"), save_csv(records, "adp_production_records.csv"), save_csv(quality, "adp_cycle_quality.csv")]
    products.append(save_csv(pd.DataFrame([{k: v for k, v in item.items() if k not in {"columns", "missing_by_column"}} for item in inventory]), "adp_file_inventory.csv"))
    summary = {
        "archive_sha256": EXPECTED_SHA, "source_manifest_unchanged": "data/raw/adp/source_manifest.json",
        "farm_id_note": "farm_group_id is a conservative province/city/numeric-code surrogate across crops, not a verified unique physical-farm identifier",
        "cultivation_rows": len(cycles), "farm_groups_conservative": cycles.farm_group_id.nunique(),
        "farm_crop_groups": len(cultivation[["도", "시군", "품목", "농가명"]].drop_duplicates()),
        "production_rows": len(records), "cycles_with_production": records.cycle_id.nunique(),
        "crop_cycle_counts": cycles.crop.value_counts().to_dict(),
        "production_cycle_counts": records.groupby("crop").cycle_id.nunique().to_dict(),
        "raw_exact_duplicate_rows_after_first": int(records.exact_duplicate_after_first.sum()),
        "before_planting_rows": int(records.before_planting.sum()),
        "kg_per_m2_target_eligible_cycles": 0,
        "aggregation_performed": False, "unit_conversion_performed": False,
        "products": products,
    }
    (RAW / "preparation_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
