"""Collect the anonymous KAMIS monthly wholesale web tables, not the key API.

The public form parameters and anonymous dropdown URLs are visible in the
official HTML/JavaScript. No session, login, browser cookies, or API key is used.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/kamis"
PROCESSED = ROOT / "data/processed"
BASE = "https://www.kamis.or.kr"
PAGE = BASE + "/customer/price/wholesale/period.do"
CODE_URL = BASE + "/common/pr_priceinfo_codelist.do"
YEARS = range(2021, 2026)
ITEMS = {"223": "오이", "225": "토마토", "226": "딸기", "256": "파프리카", "422": "방울토마토"}


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url: str, name: str) -> tuple[str, dict]:
    """Reuse a byte-verified local snapshot; otherwise download a public URL."""
    path = RAW / name
    meta_path = RAW / (name + ".metadata.json")
    if path.exists() and meta_path.exists():
        payload = path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["source_url"] == url and meta["sha256"] == hashlib.sha256(payload).hexdigest():
            return payload.decode("utf-8"), meta
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        payload = response.read()
        meta = {
            "source_url": url,
            "resolved_url": response.url,
            "http_method": "GET",
            "http_status": response.status,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "access": "anonymous_public_web_form_no_cookie_no_api_key",
        }
    payload.decode("utf-8")  # Do not silently replace text that failed to decode.
    path.write_bytes(payload)
    save_json(meta_path, meta)
    return payload.decode("utf-8"), meta


def plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def section(markup: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", markup, re.S)
    if not match:
        raise ValueError(f"Missing {tag} in source table")
    return match.group(1)


def parse_tables(markup: str, item: str, kind: dict, meta: dict) -> tuple[list[dict], list[dict]]:
    """Preserve source month cells and distinguish absent rows from dash cells."""
    monthly, annual = [], []
    tables = re.findall(r'<table\b[^>]*id="(itemTable_\d+)"[^>]*>(.*?)</table>', markup, re.S)
    if len(tables) != 2:
        raise ValueError(f"Expected two grade tables, got {len(tables)}: {item}/{kind}")
    for table_id, table in tables:
        caption = plain(section(table, "caption"))
        if any(token not in caption for token in ("중도매인 판매가격", ITEMS[item], kind["name"])):
            raise ValueError(f"Unexpected table identity/unit: {caption}")
        grade_match = re.search(r",\s*(상품|중품)\s*,\s*(\S+)\s+기간별/월간", caption)
        if not grade_match:
            raise ValueError(f"Unrecognized grade: {caption}")
        headings = [plain(x) for x in re.findall(r"<th\b[^>]*>(.*?)</th>", section(table, "thead"), re.S)][1:]
        year_columns = {index: int(text[:-1]) for index, text in enumerate(headings) if re.fullmatch(r"20\d{2}년", text)}
        if not set(YEARS).issubset(set(year_columns.values())):
            raise ValueError(f"Missing requested year columns: {headings}")
        source_unit = grade_match.group(2)
        common = {
            "crop": ITEMS[item], "item_code": item, "variety": kind["name"],
            "kind_code": kind["code"], "grade": grade_match.group(1),
            "price_type": "중도매인 판매가격", "product_class_code": "02",
            "region": "전체지역(공개조회)", "county_code": "", "unit": f"원/{source_unit}",
            "source_unit": source_unit, "kg_unit_confirmed": source_unit == "1kg",
            "convert_kg_yn": "Y", "source_url": meta["source_url"],
            "source_file": meta["source_file"], "source_sha256": meta["sha256"],
            "downloaded_at_utc": meta["downloaded_at_utc"],
            "source_table_id": table_id, "source_caption": caption,
        }
        cells = {}
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", section(table, "tbody"), re.S):
            label = plain(section(row, "th"))
            values = [plain(x) for x in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
            if len(values) != len(headings):
                raise ValueError(f"Header/cell count mismatch: {label}")
            month_match = re.fullmatch(r"(0?[1-9]|1[0-2])월", label)
            if not month_match and label != "연평균":
                raise ValueError(f"Unexpected source row: {label}")
            for index, year in year_columns.items():
                if year not in YEARS:
                    continue
                raw = values[index]
                numeric = raw.replace(",", "")
                if raw == "-":
                    price, status = None, "source_dash"
                elif numeric.isdigit() and int(numeric) > 0:
                    price, status = int(numeric), "observed"
                else:
                    raise ValueError(f"Unexpected price cell: {raw}")
                record = dict(common, year=year, price_krw_per_source_unit=price,
                              price_krw_per_kg=price if source_unit == "1kg" else None,
                              observation_status=status, source_cell=raw,
                              source_row_label=label, source_column_label=headings[index])
                if label == "연평균":
                    annual.append(record)
                else:
                    month = int(month_match.group(1))
                    key = (year, month)
                    if key in cells:
                        raise ValueError(f"Duplicate source month: {key}")
                    cells[key] = dict(record, month=month, year_month=f"{year}-{month:02d}")
        for year in YEARS:
            for month in range(1, 13):
                monthly.append(cells.get((year, month), dict(
                    common, year=year, month=month, year_month=f"{year}-{month:02d}",
                    price_krw_per_source_unit=None, price_krw_per_kg=None,
                    observation_status="month_row_not_listed",
                    source_cell="", source_row_label="", source_column_label=f"{year}년")))
    return monthly, annual


def write_csv(name: str, rows: list[dict]) -> None:
    path = PROCESSED / name
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    manifest, monthly, annual = [], [], []
    for url, name in [
        (PAGE, "wholesale_period_public.html"),
        (BASE + "/js/customer/price/wholesale/period_yearly.js", "period_yearly.js"),
        (BASE + "/js/customer/price/wholesale/item_common.js", "item_common.js"),
        (BASE + "/js/customer/iteminfo_util_new.js", "iteminfo_util_new.js"),
    ]:
        _, meta = fetch(url, name)
        manifest.append(meta)
    code_params = dict(action="getItemcodeList", productclscode="02", itemcategorycode="200", yyyy="2025")
    raw_codes, meta = fetch(CODE_URL + "?" + urlencode(code_params), "vegetable_item_codes.json")
    manifest.append(meta)
    known_items = {row["code"]: row["name"] for row in json.loads(raw_codes)}
    if any(known_items.get(code) != name for code, name in ITEMS.items()):
        raise ValueError("Public crop dropdown differs from expected names/codes")
    for item in ITEMS:
        kind_params = dict(action="getKindcodeList", productclscode="02", itemcode=item,
                           pepper_all_yn="Y", yyyy="2025")
        raw_kinds, meta = fetch(CODE_URL + "?" + urlencode(kind_params), f"kind_codes_{item}.json")
        manifest.append(meta)
        for kind in json.loads(raw_kinds):
            query = dict(action="monthly", actionUrl="/customer/price/wholesale/period.do", yyyy="2025",
                         period="5", itemcategorycode="200", itemcode=item, kindcode=kind["code"],
                         productrankcode="0", countycode="", convert_kg_yn="Y")
            markup, meta = fetch(PAGE + "?" + urlencode(query), f"monthly_{item}_{kind['code']}_2021_2025.html")
            month_rows, year_rows = parse_tables(markup, item, kind, meta)
            monthly.extend(month_rows)
            annual.extend(year_rows)
            meta = dict(meta, requested_years=list(YEARS), monthly_grid_rows=len(month_rows),
                        observed_month_cells=sum(row["observation_status"] == "observed" for row in month_rows))
            manifest.append(meta)
            print(f"{ITEMS[item]}/{kind['name']}: {meta['observed_month_cells']} observed month cells", flush=True)
    keys = [(r["item_code"], r["kind_code"], r["grade"], r["year_month"]) for r in monthly]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate normalized monthly keys")
    write_csv("kamis_wholesale_monthly.csv", monthly)
    write_csv("kamis_wholesale_monthly_kg.csv", [row for row in monthly if row["kg_unit_confirmed"]])
    write_csv("kamis_wholesale_annual_source.csv", annual)
    save_json(RAW / "source_manifest.json", manifest)
    validation = {
        "monthly_grid_rows": len(monthly), "source_annual_rows": len(annual),
        "status_counts": dict(Counter(r["observation_status"] for r in monthly)),
        "unique_crops": len({r["crop"] for r in monthly}),
        "unique_item_varieties": len({(r["item_code"], r["kind_code"]) for r in monthly}),
        "duplicate_keys": 0,
        "observed_counts_by_crop": dict(Counter(r["crop"] for r in monthly if r["observation_status"] == "observed")),
        "source_unit_grid_counts": dict(Counter(r["source_unit"] for r in monthly)),
        "kg_grid_rows": sum(r["kg_unit_confirmed"] for r in monthly),
        "kg_observed_rows": sum(r["price_krw_per_kg"] is not None for r in monthly),
        "source_year_filter": "Response includes 2020-2025 and normal-year column; keep 2021-2025 only.",
        "monthly_missing_policy": "Blank numeric value; preserve source_dash vs month_row_not_listed. No imputation.",
        "price_semantics": "Intermediary wholesale selling price; not farmgate price or farmer income.",
    }
    save_json(RAW / "extraction_validation.json", validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
