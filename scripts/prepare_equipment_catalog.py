"""Normalize three audited Smart Farm Korea public package-price tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "5126": "CRONOUS-AV-CR01 환경제어 구성",
    "6337": "옹달샘300 양액 공급 구성",
    "6688": "MAGMA1000V20 양액기",
}


def price(value: str) -> int | None:
    text = value.replace("원", "").replace(",", "").strip()
    return None if text == "-" else int(text)


def build_catalog(source: list[dict]) -> dict:
    packages = {}
    for record in source:
        equipment_id = record["equipment_id"]
        if equipment_id in packages:
            raise ValueError(f"Duplicate equipment source: {equipment_id}")
        base_table, option_table = record["price_tables"]
        total = price(base_table[-1][-1])
        if base_table[-1][0] != "합계" or total is None or total < 0:
            raise ValueError(f"Published package total missing: {equipment_id}")
        components = []
        for row in base_table[1:-1]:
            components.append({
                "name": row[1], "model": row[2], "specification": row[3],
                "displayed_quantity": row[4], "displayed_price_krw": price(row[-1]),
            })
        options = []
        for index, row in enumerate(option_table[1:-1], start=1):
            amount = price(row[-1])
            if amount is not None:
                options.append({
                    "option_id": f"{equipment_id}-option-{index}", "name": row[1],
                    "model": row[2], "specification": row[3], "price_krw": amount,
                })
        packages[equipment_id] = {
            "equipment_id": equipment_id, "name": NAMES[equipment_id],
            "category": "environment_control" if equipment_id == "5126" else "fertigation",
            "package_price_krw": total, "components_for_reference_only": components,
            "options": options, "published_options_total_krw": price(option_table[-1][-1]),
            "source_url": record["source_url"], "request_method": record["request_method"],
            "request_parameters": {"eqpmnSeq": equipment_id},
            "catalog_url": "https://www.smartfarmkorea.net/company/equipmentInfo.do",
            "checked_date": record["checked_date"],
            "price_basis": "published_package_total",
            "vat_included": None, "installation_included": None,
        }
    return {
        "currency": "KRW", "packages": packages,
        "limitations": [
            "업체 등록 표준가격이며 실제 계약·설치 견적이 아닙니다.",
            "등록가격의 부가세·설치비 포함 여부는 확인되지 않았습니다.",
            "구성품 가격을 재합산하지 않고 공개된 묶음 합계를 사용합니다.",
            "옵션은 명시적으로 선택하며 선택한 옵션은 묶음 수량만큼 계산합니다.",
            "장비 간 호환성, 재배면적별 필요 수량, 수확 증가 효과와 수명은 검증되지 않았습니다.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "reports/equipment_source_check_2026-10-10.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/equipment_catalog.json")
    args = parser.parse_args()
    catalog = build_catalog(json.loads(args.source.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(catalog['packages'])} equipment packages: {args.output}")


if __name__ == "__main__":
    main()
