"""Write the current farm linkage evidence without modifying model artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from src.farm_evidence import load_farm_evidence  # noqa: E402


def render_report(evidence: dict) -> str:
    api, cases = evidence["api"], evidence["public_cases"]
    counts = api["counts"]
    lines = [
        "# 같은 농가·작기의 생산과 경영 자료 연결 검증",
        "",
        "현재 원 CSV를 다시 읽어 키·산술·해시를 검사한 결과입니다. 모델을 새로 학습하거나 기존 모델 파일을 변경하지 않습니다.",
        "",
        "## API에서 실제 연결되는 범위",
        "",
        f"출하 기록 {counts['output_rows']:,}행, 비용 기록 {counts['cost_rows']:,}행을 각각 시설·작기 키로 먼저 묶었습니다.",
        f"출하가 있는 {counts['output_cycles']}작기 중 비용 기록도 존재하는 작기는 **{counts['overlap_cycles']}작기 / {counts['overlap_facilities']}시설**입니다.",
        f"그중 **딸기는 {counts['strawberry_overlap_cycles']}작기**이며, 전체 비용 범위와 수집 완료가 확인된 작기는 **0작기**입니다.",
        "",
        "시설ID만으로 합치지 않습니다. 시설ID+작기번호가 유일한 연도·작기 설명으로 확인될 때만 연결합니다. 서로 다른 연도·작기 설명으로 대응되면 거부합니다. 원 출하행×비용행을 조인하지 않아 다대다 행 증식과 비용 중복 합산이 없습니다.",
        "",
        "| 시설ID | 작기번호 | 작기연도 | 품목 | 출하 행 | 비용 행 | 전체 비용 |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for row in api["cycle_evidence"]:
        if row["has_both_record_types"]:
            lines.append(f"| {row['facility_id']} | {row['cycle_number']} | {row['cycle_year']} | {row['crop']} | {row['output_rows']} | {row['cost_rows']} | 미확인 |")
    lines += ["", *[f"- {value}" for value in api["limits"]], "", "## 공개 보고서에서 확보한 같은 농가 경영 사례", ""]
    lines += [
        f"경기도 2023년 시범농가 {cases['source_rows']}사례 중 조수입−경영비=소득을 원 값으로 검산해 {len(cases['accepted_cases'])}사례를 통과시키고 {len(cases['excluded_cases'])}사례를 제외했습니다.",
        "시설표와 소득표의 동일 보고서 사례 연결입니다. GG2023 사례ID는 이 보고서 행에서 만든 식별자이며 API 시설ID가 아닙니다.",
        "",
        "| 통과한 딸기 사례 | 면적 | 조수입 | 경영비 | 보고 소득 | 기준 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in cases["strawberry_cases"]:
        lines.append(f"| {row['case_id']} / {row['city']} | {row['area_m2']:,.0f}㎡ | {row['revenue_krw_per_1000m2']:,.0f}원 | {row['operating_cost_krw_per_1000m2']:,.0f}원 | {row['income_krw_per_1000m2']:,.0f}원 | 1,000㎡당, 기간 미확인 |")
        lines += ["", f"출처: [경기도농업기술원 공식 보고서]({row['source_url']}), PDF {row['source_pdf_pages']}쪽 / 인쇄 {row['source_printed_pages']}쪽, 소득표 {row['source_income_row']}행.", ""]
    lines += ["제외한 사례:", ""]
    lines += [f"- {row['case_id']} / {row['city']}: {', '.join(row['reasons'])}" for row in cases["excluded_cases"]]
    lines += ["", *[f"- {value}" for value in cases["limits"]], "", "## 이 근거로 할 수 있는 일", "",
              "실제로 한 농가에 연결된 시설 특성과 보고 매출·경영비·소득 사례를 확인하고 계산을 검산할 수 있습니다. API 비용은 해당 시설·작기에 기록이 존재하는지 확인할 수 있습니다.", "",
              "딸기 출하량 예측값에 해당 딸기 농가의 완결 운영비·투자비를 연결한 검증은 아직 성립하지 않습니다. 평택 사례는 API 출하 모델과 다른 농가이고, 연간 기간과 전체 투자비가 없으므로 모델 정확도나 투자 회수기간을 실증한 것으로 표시하지 않습니다.", "",
              "## 원본 식별자", "", "| 현재 CSV | 행 수 | SHA256 |", "|---|---:|---|"]
    lines += [f"| {row['path']} | {row['rows']} | `{row['sha256']}` |" for row in evidence["input_files"]]
    lines += ["", "재현: `.venv/Scripts/python.exe scripts/audit_farm_economics_evidence.py`", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    args = parser.parse_args()
    evidence = load_farm_evidence(args.project)
    reports = args.project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "farm_economics_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (reports / "farm_economics_evidence.md").write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({"api": evidence["api"]["counts"], "accepted_public_cases": len(evidence["public_cases"]["accepted_cases"]), "accepted_strawberry_cases": len(evidence["public_cases"]["strawberry_cases"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
