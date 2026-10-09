"""Collect the official 2026 greenhouse planning reference, not market quotes."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/capex"
PAGE_URL = "https://www.mafra.go.kr/bbs/home/791/577560/artclView.do"
FILE_URL = "https://www.mafra.go.kr/bbs/home/791/596350/download.do"


def download(url: str, path: Path) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (public-data-research)"})
    with urlopen(request, timeout=45) as response:
        content = response.read()
        entry = {"url": url, "resolved_url": response.url, "http_status": response.status,
                 "content_type": response.headers.get("Content-Type", "")}
    path.write_bytes(content)
    return {**entry, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "file": path.relative_to(ROOT).as_posix()}


def paragraphs(path: Path) -> dict[str, str]:
    result = {}
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("Contents/section") and name.endswith(".xml"):
                tree = etree.fromstring(archive.read(name))
                for index, paragraph in enumerate(tree.xpath('//*[local-name()="p"]'), 1):
                    # Only this paragraph's runs; do not duplicate nested table paragraphs.
                    texts = paragraph.xpath('./*[local-name()="run"]/*[local-name()="t"]//text()')
                    text = re.sub(r"\s+", " ", " ".join(texts)).strip()
                    if text:
                        result[f"{name}:p{index:04d}"] = text
    return result


def unique_match(items: dict[str, str], pattern: str) -> tuple[str, str, re.Match]:
    found = [(key, value, re.search(pattern, value)) for key, value in items.items()]
    found = [(key, value, match) for key, value, match in found if match is not None]
    if len(found) != 1:
        raise ValueError(f"Expected one source match for {pattern!r}, got {len(found)}")
    return found[0]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    target = ROOT / "data/processed/capex_reference.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = RAW / "2026_greenhouse_guideline.hwpx"
    manifest = [download(PAGE_URL, RAW / "mafra_notice.html"), download(FILE_URL, source)]
    (RAW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    items = paragraphs(source)
    (RAW / "2026_greenhouse_guideline_extracted.txt").write_text(
        "\n".join(f"{key}\t{value}" for key, value in items.items()), encoding="utf-8")
    unit_ref, unit_quote, units = unique_match(
        items, r"기준 단가: 철골\(유리·경질판\) ([\d,]+)백만원/ha, 파이프\(비닐\) ([\d,]+)백만원/ha")
    rate_ref, rate_quote, rates = unique_match(
        items, r"지원형태: 국비보조 (\d+)%, 지방비 (\d+)%, 자부담\(융자 최대 (\d+)% 포함\) (\d+)%")
    area_ref, area_quote, areas = unique_match(items, r"지원시설 규모\s*:\s*([\d.]+)ha～([\d.]+)ha")
    caveat_ref, caveat_quote, _ = unique_match(items, r"사업 계획 수립을 위한 예시 기준")
    national, local, loan, owner = (int(value) / 100 for value in rates.groups())
    output = []
    for facility, value in zip(("철골(유리·경질판)", "파이프(비닐)"), units.groups()):
        million_won = int(value.replace(",", ""))
        output.append({
            "guideline_year": 2026, "facility_type": facility,
            "reference_million_krw_per_ha": million_won,
            "reference_krw_per_m2": million_won * 1_000_000 / 10_000,
            "value_type": "official_planning_example_not_market_quote",
            "eligible_area_min_m2": float(areas.group(1)) * 10_000,
            "eligible_area_max_m2": float(areas.group(2)) * 10_000,
            "national_grant_fraction": national, "local_grant_fraction": local,
            "owner_financing_fraction_including_loan": owner, "loan_fraction_max": loan,
            "owner_cash_fraction_at_max_loan": round(owner - loan, 10),
            "auto_apply_grant": "false", "training_eligible": "false",
            "includes": "온실 신개축 및 ICT·연계시설; 위탁설계형 설계비 포함",
            "excludes": "토지·부지조성; 임차료; 전기인입 200m 초과; 냉난방 본체; 농기계; 저온유통차량; 선별기; 숙소·식당 등",
            "conditions": "개별 선정·지자체 예산·대출심사 확인 필요; 하나의 연동 또는 연접 단동; 자가설계비 별도",
            "unit_source_locator": unit_ref, "unit_source_quote": unit_quote,
            "rate_source_locator": rate_ref, "rate_source_quote": rate_quote,
            "area_source_locator": area_ref, "area_source_quote": area_quote,
            "caveat_source_locator": caveat_ref, "caveat_source_quote": caveat_quote,
            "source_page_url": PAGE_URL, "source_file_url": FILE_URL,
            "source_sha256": manifest[1]["sha256"], "license": "KOGL_Type_1_attribution",
        })
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(f"Saved {len(output)} official planning reference rows; no grant applied.")


if __name__ == "__main__":
    main()
