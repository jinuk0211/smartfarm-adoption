"""Preserve anonymous public evidence and normalize published yield summaries.

No login, authentication endpoint, API key, or gated download is used. Published
group summaries are reference values, never farm-level model training examples.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from lxml import html


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/smartfarm_public"
PROCESSED = ROOT / "data/processed"
SOURCES = {
    "rda_tomato": "https://adp.rda.go.kr/portal/pub/idc/tomatoData.do",
    "rda_strawberry": "https://adp.rda.go.kr/portal/pub/idc/strawberryData.do",
    "rda_cucumber": "https://adp.rda.go.kr/portal/pub/idc/cucumberData.do",
    "rda_2024_dataset": "https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE",
    "smartfarm_catalog": "https://www.smartfarmkorea.net/datamart/fclty/list.do?menuId=M11040101",
    "smartfarm_api_schema": "https://www.smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030105",
    "smartfarm_guide": "https://www.smartfarmkorea.net/contents/view.do?menuId=M110501",
    "smartfarm_download_ui": "https://www.smartfarmkorea.net/static/js/common.js",
    "rda_download_ui": "https://adp.rda.go.kr/js/portal/data/dataPblcateDetail.js",
    "rda_identity_ui": "https://adp.rda.go.kr/js/portal/data/commData.js",
}
REFERENCE_SPECS = {
    "rda_tomato": ("토마토", 3.3, "kg/3.3㎡", "2016~2022 작기; 원문 6개년", 3),
    "rda_strawberry": ("딸기", 1000.0, "kg/10a", "2017~2022 작기; 원문 5개년", 2),
    "rda_cucumber": ("오이", 3.3, "kg/3.3㎡", "2021~2023 작기; 원문 3개년", 1),
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def annual_table(body: bytes) -> list[list[str]]:
    document = html.fromstring(body.decode("utf-8"))
    tables = [
        table for table in document.xpath("//table")
        if "연간 생산량 차이" in " ".join(table.xpath("./caption//text()"))
    ]
    if len(tables) != 1:
        raise ValueError(f"Expected one annual yield table, got {len(tables)}")
    return [
        [clean(cell.text_content()) for cell in row.xpath("./th|./td")]
        for row in tables[0].xpath(".//tr")
    ]


def yield_rows(source_id: str, body: bytes, sha256: str) -> list[dict]:
    crop, denominator, unit, period, expected_rows = REFERENCE_SPECS[source_id]
    rows = annual_table(body)
    headers, values = rows[0], rows[1:]
    if len(values) != expected_rows:
        raise ValueError(f"{source_id}: unexpected row count {len(values)}")
    if "평균" not in " ".join(headers) or "20%" not in " ".join(headers):
        raise ValueError(f"{source_id}: unexpected headers {headers}")
    result = []
    for row in values:
        for position, header in enumerate(headers[1:4 if source_id != "rda_strawberry" else 5], 1):
            if source_id == "rda_cucumber":
                quantity = float(row[position])
                # Published columns: mean, bottom 20%, top 20%, N, top N, bottom N.
                count = int(row[{1: 4, 2: 6, 3: 5}[position]])
            else:
                match = re.fullmatch(r"([\d,.]+)\s*\((\d+)\)", row[position])
                if match is None:
                    raise ValueError(f"{source_id}: unrecognized value {row[position]!r}")
                quantity = float(match.group(1).replace(",", ""))
                count = int(match.group(2))
            result.append({
                "crop": crop,
                "facility_or_cultivation_group": row[0],
                "published_statistic": re.sub(r"\s*\(?농가\s*수\)?", "", header).strip(),
                "yield_kg_per_published_area": quantity,
                "published_unit": unit,
                "area_denominator_m2": denominator,
                "yield_kg_per_m2": round(quantity / denominator, 8),
                "reported_group_count": count,
                "count_interpretation": "원문 농가수; 고유농가/작기 반복 여부 미확인",
                "period_as_published": period,
                "data_scope": "published_group_summary",
                "training_eligible": "false",
                "is_synthetic": "false",
                "statistical_caveat": "상하위 그룹 요약값이며 개별 농가 백분위 경계/예측구간이 아님",
                "source_url": SOURCES[source_id],
                "source_file": f"data/raw/smartfarm_public/{source_id}.html",
                "source_sha256": sha256,
            })
    return result


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    manifest = []
    bodies = {}
    for source_id, url in SOURCES.items():
        extension = ".js" if url.endswith(".js") else ".html"
        path = RAW / f"{source_id}{extension}"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (public-data-research)"})
        entry = {"source_id": source_id, "requested_url": url,
                 "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                 "training_eligible": False}
        try:
            with urlopen(request, timeout=40) as response:
                body = response.read()
                entry.update({"http_status": response.status, "resolved_url": response.url,
                              "content_type": response.headers.get("Content-Type", "")})
            path.write_bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            entry.update({"status": "saved", "bytes": len(body), "sha256": digest,
                          "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                          "content_role": "public_reference_statistics" if source_id in REFERENCE_SPECS
                          else "metadata_or_public_access_requirement_evidence"})
            bodies[source_id] = (body, digest)
        except (OSError, ValueError) as error:
            entry.update({"status": "failed", "error": str(error)})
        manifest.append(entry)
        print(f"{source_id}: {entry['status']}", flush=True)
    (RAW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = set(REFERENCE_SPECS) - bodies.keys()
    if missing:
        raise RuntimeError(f"Missing reference pages: {sorted(missing)}")
    normalized = []
    for source_id in REFERENCE_SPECS:
        normalized.extend(yield_rows(source_id, *bodies[source_id]))
    target = PROCESSED / "smartfarm_yield_reference_groups.csv"
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(normalized[0]))
        writer.writeheader()
        writer.writerows(normalized)
    print(f"Saved {len(normalized)} published summary rows; 0 farm-level training rows.")


if __name__ == "__main__":
    main()
