"""Collect official RDA income publications and extract greenhouse crop tables.

Rows are published aggregates, not individual farms or smart-farm adoption effects.
Requires pypdf; optionally uses PyMuPDF for faster text extraction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "rda"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
BASE = "https://www.nongsaro.go.kr"
# These attachment IDs were read from the linked official publication pages.
SOURCES = {
    2024: (842, "BS000000045358", 0, 1),
    2023: (833, "BS000000042398", 6, 5),
    2022: (819, "BS000000039491", 1, 8),
    2021: (806, "BS000000037735", 12, 10),
    2020: (803, "BS000000034135", 5, 4),
}
CROPS = ("방울토마토", "파프리카", "토마토", "딸기", "오이")
NUMBER = r"[0-9][0-9,]*(?:\.[0-9]+)?"
FIELDS = [
    "year", "crop", "crop_original", "cultivation_type", "region",
    "area_m2", "period_basis", "yield_kg_per_1000m2",
    "revenue_krw_per_1000m2", "operating_cost_krw_per_1000m2",
    "depreciation_krw_per_1000m2", "equipment_depreciation_krw_per_1000m2",
    "facility_depreciation_krw_per_1000m2", "family_labor_cost_krw_per_1000m2",
    "family_labor_hours_per_1000m2", "hired_labor_cost_krw_per_1000m2",
    "hired_labor_hours_per_1000m2", "energy_water_cost_krw_per_1000m2",
    "farmgate_price_krw_per_kg", "income_krw_per_1000m2",
    "main_product_revenue_krw_per_1000m2",
    "production_cost_krw_per_1000m2", "source_url", "source_page",
    "source_printed_page", "source_file", "source_sha256", "source_scope",
    "observation_unit", "license", "schema_regime", "parse_notes",
]


def get_bytes(url: str) -> bytes:
    with urlopen(url, timeout=90) as response:
        return response.read()


def download(year: int, scope: str) -> dict:
    post, group, national, regional = SOURCES[year]
    serial = national if scope == "national" else regional
    url = f"{BASE}/portal/bsFileDownload.do?atchmnflGroupEsntlCode={group}&atchmnflSn={serial}"
    page_url = f"{BASE}/portal/ps/pst/pstb/pstbc/mngmtDtaDtl.ps?nttSn={post}"
    path = RAW / f"{year}_{scope}.pdf"
    metadata_path = path.with_suffix(".json")
    if path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]:
            return metadata
    publication_path = RAW / f"{year}_publication.html"
    if not publication_path.exists():
        publication_path.write_bytes(get_bytes(page_url))
    publication = publication_path.read_text(encoding="utf-8")
    # Record the specific posted license, not a site-wide assumption.
    mark = re.search(r'id="openGradeTitle"[^>]*>(.*?)</span>', publication, re.S)
    license_text = re.sub(r"<[^>]+>", "", mark[1]).strip() if mark else "not parsed"
    data = get_bytes(url)
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Expected PDF: {url}")
    path.write_bytes(data)
    metadata = {
        "year": year, "scope": scope, "url": url,
        "source_page_url": page_url, "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
        "local_path": str(path), "license": license_text,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def texts(path: Path) -> list[str]:
    cache = path.with_suffix(".pages.json")
    cache_hash = path.with_suffix(".pages.sha256")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if cache.exists() and cache_hash.exists() and cache_hash.read_text(encoding="ascii") == source_hash:
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        import pymupdf
    except ImportError:
        pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    else:
        with pymupdf.open(path) as document:
            pages = [page.get_text() for page in document]
    cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    cache_hash.write_text(source_hash, encoding="ascii")
    return pages


def numeric(value: str | None) -> float | None:
    return float(value.replace(",", "")) if value else None


def value_after(text: str, label: str) -> float | None:
    match = re.search(re.escape(label) + f"({NUMBER})", text)
    return numeric(match[1]) if match else None


def labor(text: str, label: str) -> tuple[float | None, float | None]:
    match = re.search(re.escape(label) + f"({NUMBER})시간({NUMBER})", text)
    return (numeric(match[1]), numeric(match[2])) if match else (None, None)


def extract_row(raw_text: str, meta: dict, page_number: int) -> dict | None:
    text = re.sub(r"\s+", "", raw_text).replace("·", "").replace("․", "")
    if "주산물가액" not in text or "자가노동비" not in text or "비목별" not in text:
        return None
    # Separate multi-column farm-size summaries repeat the national aggregates.
    if "주산물수량" in text and ("㏊" in text or "ha" in text):
        return None
    basis = re.search(r"\(기준[:：]([^)]*)\)", text)
    if not basis or "10a" not in basis[1]:
        return None
    header = text[:basis.start()]
    header = re.sub(r"^-\d+-", "", header)
    crop = next((name for name in CROPS if name in header), None)
    if not crop or "노지" in header:
        return None
    # All selected tables are greenhouse crops; early editions name crop/forcing type.
    crop_pattern = r"(?:시설)?" + crop + r"(?:\([^)]*\))?"
    if crop == "파프리카":
        crop_pattern = r"(?:시설)?(?:착색단고추\(파프리카\)|파프리카(?:\(착색단고추\))?)"
    crop_match = re.search(crop_pattern, header)
    if not crop_match:
        return None
    crop_original = crop_match[0]
    region = "전국" if meta["scope"] == "national" else header[crop_match.end():]
    if not region or len(region) > 12:
        raise ValueError(f"Unrecognized region {header!r} on {meta['local_path']}:{page_number}")
    cultivation = re.search(r"\(([^)]*)\)", crop_original)
    cultivation_type = cultivation[1] if cultivation else "방식미표기"
    if crop == "파프리카":
        cultivation_type = "방식미표기"  # Parentheses give a crop synonym, not a growing method.
    main = re.search(r"주산물가액(" + NUMBER + r")(?:㎏|kg)([0-9,.]+)", text)
    revenue_match = re.search(r"부산물가액.*?계(" + NUMBER + r")", text)
    operating_match = re.search(r"계(" + NUMBER + r")자가노동비", text)
    production_match = re.search(r"토지자본용역비.*?계(" + NUMBER + r")부가가치", text)
    if not main or not revenue_match or not operating_match:
        raise ValueError(f"Missing essential table fields on {meta['local_path']}:{page_number}")
    revenue_raw = revenue_match[1]
    combined = main[2]
    price = None
    main_revenue = None
    notes = []
    main_raw = re.search(
        r"주\s*산\s*물\s*가\s*액\s*(" + NUMBER + r")\s*(?:㎏|kg)\s*(" + NUMBER + r")\s+(" + NUMBER + r")",
        raw_text,
    )
    if main_raw:
        price = numeric(main_raw[2])
        main_revenue = numeric(main_raw[3])
    elif combined.endswith(revenue_raw) and len(combined) > len(revenue_raw):
        price = numeric(combined[:-len(revenue_raw)])
        main_revenue = numeric(revenue_raw)
    else:
        notes.append("farmgate_price_unparsed_or_byproduct_income")
    equipment = value_after(text, "대농구상각비")
    facility = value_after(text, "영농시설상각비")
    family_hours, family_cost = labor(text, "자가노동비")
    hired_hours, hired_cost = labor(text, "고용노동비")
    row = {
        "year": meta["year"], "crop": crop, "crop_original": crop_original,
        "cultivation_type": cultivation_type, "region": region, "area_m2": 1000,
        "period_basis": basis[1], "yield_kg_per_1000m2": numeric(main[1]),
        "revenue_krw_per_1000m2": numeric(revenue_raw),
        "operating_cost_krw_per_1000m2": numeric(operating_match[1]),
        "depreciation_krw_per_1000m2": equipment + facility if equipment is not None and facility is not None else None,
        "equipment_depreciation_krw_per_1000m2": equipment,
        "facility_depreciation_krw_per_1000m2": facility,
        "family_labor_cost_krw_per_1000m2": family_cost,
        "family_labor_hours_per_1000m2": family_hours,
        "hired_labor_cost_krw_per_1000m2": hired_cost,
        "hired_labor_hours_per_1000m2": hired_hours,
        "energy_water_cost_krw_per_1000m2": value_after(text, "수도광열비"),
        "farmgate_price_krw_per_kg": price,
        "income_krw_per_1000m2": value_after(text, "소득"),
        "main_product_revenue_krw_per_1000m2": main_revenue,
        "production_cost_krw_per_1000m2": numeric(production_match[1]) if production_match else None,
        "source_url": meta["url"], "source_page": page_number,
        "source_printed_page": (re.search(r"-\s*(\d+)\s*-", raw_text) or [None, ""])[1],
        "source_file": str(Path(meta["local_path"]).relative_to(ROOT)),
        "source_sha256": meta["sha256"], "source_scope": meta["scope"],
        "observation_unit": "published_crop_region_annual_aggregate",
        "license": meta["license"],
        "schema_regime": "2023plus_cultivation_reclassified" if meta["year"] >= 2023 else "pre2023_forcing_types",
        "parse_notes": ";".join(notes),
    }
    # Published totals differ by one won due to rounding; larger discrepancies fail.
    if row["income_krw_per_1000m2"] is not None:
        discrepancy = abs(row["revenue_krw_per_1000m2"] - row["operating_cost_krw_per_1000m2"] - row["income_krw_per_1000m2"])
        if discrepancy > 3:
            raise ValueError(f"Income reconciliation failed by {discrepancy} on page {page_number}")
    if price is not None:
        discrepancy = abs(price * row["yield_kg_per_1000m2"] / main_revenue - 1)
        if discrepancy > 0.015:
            raise ValueError(f"Price/yield reconciliation failed on page {page_number}")
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=list(SOURCES))
    args = parser.parse_args()
    for path in [RAW, PROCESSED, REPORTS]:
        path.mkdir(parents=True, exist_ok=True)
    manifest, rows, failures = [], [], []
    for year in args.years:
        for scope in ["national", "regional"]:
            meta = download(year, scope)
            pages = texts(Path(meta["local_path"]))
            count = 0
            for index, page in enumerate(pages, start=1):
                try:
                    row = extract_row(page, meta, index)
                except ValueError as error:
                    failures.append({"year": year, "scope": scope, "page": index, "error": str(error)})
                    continue
                if row:
                    rows.append(row)
                    count += 1
            meta.update({"pages": len(pages), "extracted_rows": count})
            manifest.append(meta)
            print(f"{year} {scope}: {count} rows, {len(pages)} pages", flush=True)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["year"], row["region"], row["crop_original"])].append(row)
    excluded = []
    rows = []
    for group in groups.values():
        if len(group) == 1:
            rows.extend(group)
        else:
            # Preserve both conflicting source rows; do not guess which title is wrong.
            for row in group:
                excluded.append({**row, "exclusion_reason": "duplicate_crop_region_year_with_conflicting_values"})
    with (PROCESSED / "rda_excluded_rows.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS + ["exclusion_reason"])
        writer.writeheader()
        writer.writerows(excluded)
    with (PROCESSED / "rda_crop_income.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (RAW / "extraction_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    for meta in manifest:
        meta["usable_rows"] = sum(r["year"] == meta["year"] and r["source_scope"] == meta["scope"] for r in rows)
        meta["excluded_conflicting_rows"] = sum(r["year"] == meta["year"] and r["source_scope"] == meta["scope"] for r in excluded)
    (RAW / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TOTAL {len(rows)} usable rows; {len(excluded)} conflicting rows excluded; {len(failures)} pages need review", flush=True)


if __name__ == "__main__":
    main()
