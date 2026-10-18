"""Facility-bound budgets; no automatic population-average cost substitution.

Records and quotes entered by a user remain user-declared evidence. Matching
identifiers proves a calculation's scope, not a document's authenticity or a
model's accuracy. Existing model-hashed economics code is reused unchanged.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
import math
from typing import Any

from src.economics import evaluate_plan


COST_CATEGORIES = {
    "seedlings": "종묘·종자",
    "fertilizer_crop_protection": "비료·농약·재배자재",
    "energy_water": "난방·전기·용수",
    "hired_labor": "고용노동",
    "packaging_transport": "포장·운송·판매 관련 지출",
    "rent": "임차료",
    "repairs_other": "수선·유지·기타 현금비용",
    "depreciation": "감가상각",
    "family_labor": "가족노동 기회비용",
}
SOURCE_KINDS = {"user_record", "quote", "budget", "external_reference"}


def scope_for_target(target: Mapping) -> dict:
    """Snapshot every plan attribute; never reassign existing evidence on rerun."""
    return deepcopy(dict(target))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: 내용을 입력해야 합니다")
    return value.strip()


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name}: 미입력은 0원이 아닙니다")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: 숫자를 입력해야 합니다") from exc
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f"{name}: 유효한 {'양수' if positive else '0 이상의 수'}가 필요합니다")
    return result


def _date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(_text(value, name))
    except ValueError as exc:
        raise ValueError(f"{name}: YYYY-MM-DD 날짜가 필요합니다") from exc


def _evidence(row: Mapping, target: Mapping, label: str, ledger: list) -> None:
    expected = scope_for_target(target)
    if row.get("scope") != expected:
        raise ValueError(f"{label}: 시설 또는 연간 적용기간·작기·면적·재배조건이 계획과 다릅니다")
    for key, value in target.items():
        if key in row and row[key] != value:
            raise ValueError(f"{label}: {key} 항목이 연결 대상과 다릅니다")
    kind = row.get("source_kind")
    if kind not in SOURCE_KINDS:
        raise ValueError(f"{label}: 근거 종류를 지정해야 합니다")
    source = _text(row.get("source_ref"), f"{label} 출처·계산근거")
    ledger.append({
        "label": label, "source_kind": kind, "source_ref": source,
        "scope": dict(expected), "document_verified": False,
    })


def _sales(rows: list, target: Mapping, ledger: list, prefix: str) -> float:
    if not rows:
        raise ValueError(f"{prefix}: 판매계획이 필요합니다")
    total_share, weighted_price = 0.0, 0.0
    cycle_start = _date(target["cycle_start"], "작기 시작일")
    cycle_end = _date(target["cycle_end"], "작기 종료일")
    for index, row in enumerate(rows):
        label = f"{prefix} {index + 1} {_text(row.get('label'), '판매 경로·등급')}"
        _evidence(row, target, label, ledger)
        share = _number(row.get("share"), f"{label} 출하 배분율")
        if share > 1:
            raise ValueError("출하 배분율은 0~1이어야 합니다")
        price = _number(row.get("net_price_krw_per_kg"), f"{label} 수취단가")
        start = _date(row.get("sale_start"), "판매 시작일")
        end = _date(row.get("sale_end"), "판매 종료일")
        if not cycle_start <= start <= end <= cycle_end:
            raise ValueError(f"{label}: 판매기간이 대상 작기를 벗어납니다")
        total_share += share
        weighted_price += share * price
    if not math.isclose(total_share, 1.0, abs_tol=1e-8):
        raise ValueError(f"{prefix}: 출하 배분율 합계가 100%여야 합니다")
    return weighted_price


def _costs(rows: list, target: Mapping, ledger: list, prefix: str) -> dict:
    categories = [row.get("category") for row in rows]
    if len(categories) != len(set(categories)):
        raise ValueError(f"{prefix}: 중복 비용항목이 있습니다")
    if set(categories) != set(COST_CATEGORIES):
        missing = set(COST_CATEGORIES) - set(categories)
        names = ", ".join(COST_CATEGORIES[name] for name in sorted(missing))
        raise ValueError(f"{prefix}: 필수 비용항목을 모두 입력하세요 ({names})")
    fixed, variable, depreciation, family = 0.0, 0.0, 0.0, 0.0
    for row in rows:
        category = row["category"]
        label = f"{prefix} {COST_CATEGORIES[category]}"
        _evidence(row, target, label, ledger)
        amount = _number(row.get("amount_krw"), label)
        basis = row.get("basis")
        if basis not in {"annual_total", "per_kg"}:
            raise ValueError(f"{label}: 연간 총액 또는 kg당 비용 기준이 필요합니다")
        if category in {"depreciation", "family_labor"} and basis != "annual_total":
            raise ValueError("감가상각·가족노동은 연간 총액으로 입력해야 합니다")
        if category == "depreciation":
            depreciation = amount
        elif category == "family_labor":
            family = amount
        elif basis == "annual_total":
            fixed += amount
        else:
            variable += amount
    return {"fixed_cash_krw": fixed, "variable_cash_krw_per_kg": variable,
            "depreciation_krw": depreciation, "family_labor_krw": family}


def _replacements(values: Mapping, horizon: int) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ValueError("교체비 계획이 미입력입니다. 없음 또는 연도별 금액을 명시하세요")
    result = {}
    for key, value in values.items():
        if isinstance(key, bool):
            raise ValueError("교체 연도는 양의 정수여야 합니다")
        try:
            year = int(key)
        except (ValueError, TypeError) as exc:
            raise ValueError("교체 연도는 정수여야 합니다") from exc
        if str(year) != str(key) or not 1 <= year <= horizon:
            raise ValueError("교체 연도는 분석기간 내 양의 정수여야 합니다")
        result[str(year)] = _number(value, "교체 비용")
    return result


def evaluate_facility_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Connect one predicted crop cycle to its declared facility's annual budget.

    Every cost category must be explicit, including true zeroes. Annual costs
    cover the full financial year, including non-growing months. Sales prices
    must not already deduct expenses entered again in the cost table.
    """
    target = deepcopy(payload.get("target", {}))
    for key in ("plan_id", "facility_id", "crop", "variety", "region", "district", "facility_type"):
        _text(target.get(key), key)
    area = _number(target.get("area_m2"), "대상 면적", positive=True)
    start = _date(target.get("financial_start"), "연간 시작일")
    end = _date(target.get("financial_end"), "연간 종료일")
    if (end - start).days + 1 not in {365, 366}:
        raise ValueError("재무기간은 실제 날짜 기준 1년(365/366일)이어야 합니다")
    cycle_start = _date(target.get("cycle_start"), "작기 시작일")
    cycle_end = _date(target.get("cycle_end"), "작기 종료일")
    if not start <= cycle_start <= cycle_end <= end:
        raise ValueError("한 작기의 시작·종료일이 연간 재무기간 안에 있어야 합니다")
    if payload.get("evidence_target") != target:
        raise ValueError("근거를 연결한 대상 시설·면적·품목·작기가 변경되었습니다. 적용 근거를 다시 확인하세요")
    if payload.get("acknowledge_prediction_period") is not True:
        raise ValueError("학습 출하 기록의 작기 완결 여부가 미확인임을 포함해 1작기 적용 조건을 확인하세요")
    prediction = payload.get("prediction", {})
    if (prediction.get("status"), prediction.get("target")) != ("predicted", "shipment") or prediction.get("unit") not in {"kg", "kg_per_recorded_cycle"}:
        raise ValueError("kg 단위 작기 출하량 예측이 필요합니다")
    quantity = _number(prediction.get("prediction"), "예측 출하량")
    query = prediction.get("query", {})
    if query.get("crop") != target["crop"] or not math.isclose(
        _number(query.get("area_m2"), "모델 입력 면적", positive=True), area, rel_tol=1e-9
    ):
        raise ValueError("예측 품목·면적이 대상 시설 계획과 다릅니다")
    if query.get("planting_year") != cycle_start.year or query.get("planting_month") != cycle_start.month:
        raise ValueError("예측 정식 연월이 대상 작기 시작일과 다릅니다")
    if any(query.get(key) != target[key] for key in ("variety", "region", "district", "facility_type")):
        raise ValueError("예측 품종·지역·시군구·시설유형이 비용을 적용할 대상과 다릅니다")
    horizon_value = _number(payload.get("horizon_years"), "분석기간", positive=True)
    if not horizon_value.is_integer():
        raise ValueError("분석기간은 정수 연도여야 합니다")
    horizon = int(horizon_value)
    if horizon > 1 and payload.get("repeat_annual_plan") is not True:
        raise ValueError("여러 해에 같은 연간 운영계획을 적용하는 가정을 확인하세요")
    rate = _number(payload.get("discount_rate"), "할인율")
    mode = payload.get("mode")
    if mode not in {"new", "retrofit"}:
        raise ValueError("신규 또는 기존 시설 개량 구분이 필요합니다")
    ledger: list[dict] = []
    price = _sales(payload.get("sales", []), target, ledger, "도입안 판매")
    costs = _costs(payload.get("costs", []), target, ledger, "도입안 비용")
    investments = payload.get("investments", [])
    if not investments or payload.get("investment_scope_confirmed") is not True:
        raise ValueError("설비·설치·추가 공사 비용과 포함/제외 범위를 확인해야 합니다")
    capital = 0.0
    for row in investments:
        label = _text(row.get("label"), "투자 항목")
        _evidence(row, target, label, ledger)
        _text(row.get("coverage"), "투자비 포함/제외 범위")
        capital += _number(row.get("amount_krw"), label)
    replacements = _replacements(payload.get("replacements_krw", {}), horizon)
    baseline_cash, baseline_income = 0.0, None
    baseline_replacements: dict[str, float] = {}
    baseline_budget = None
    if mode == "retrofit":
        baseline = payload.get("baseline")
        if not baseline:
            raise ValueError("개량 비교에는 같은 시설·연도의 기존 유지안 판매·비용 내역이 필요합니다")
        _evidence(baseline, target, "기존 유지안", ledger)
        baseline_quantity = _number(baseline.get("yield_kg"), "기존 유지안 출하량")
        baseline_price = _sales(baseline.get("sales", []), target, ledger, "기존 유지안 판매")
        baseline_costs = _costs(baseline.get("costs", []), target, ledger, "기존 유지안 비용")
        baseline_cash_cost = baseline_costs["fixed_cash_krw"] + baseline_quantity * baseline_costs["variable_cash_krw_per_kg"]
        baseline_cash = baseline_quantity * baseline_price - baseline_cash_cost
        baseline_income = baseline_cash - baseline_costs["depreciation_krw"]
        baseline_replacements = _replacements(baseline.get("replacements_krw", {}), horizon)
        baseline_budget = {"yield_kg": baseline_quantity, "weighted_price_krw_per_kg": baseline_price,
                           "cash_cost_krw": baseline_cash_cost, "cash_surplus_krw": baseline_cash,
                           **baseline_costs}
    scenarios = payload.get("scenarios", [])
    names = [row.get("name") for row in scenarios]
    if "기준" not in names or len(set(names)) != len(names):
        raise ValueError("중복 없는 시나리오와 '기준' 시나리오가 필요합니다")
    output, scenario_results = None, []
    for scenario in scenarios:
        name = _text(scenario.get("name"), "시나리오 이름")
        ym = _number(scenario.get("yield_multiplier"), "출하량 배율")
        pm = _number(scenario.get("price_multiplier"), "가격 배율")
        cm = _number(scenario.get("cash_cost_multiplier"), "현금비용 배율")
        if name == "기준" and (ym, pm, cm) != (1, 1, 1):
            raise ValueError("기준 시나리오의 출하량·가격·현금비용 배율은 모두 1이어야 합니다")
        q, p = quantity * ym, price * pm
        fixed = costs["fixed_cash_krw"] * cm
        variable = costs["variable_cash_krw_per_kg"] * cm
        cash_cost = fixed + q * variable
        factor = 1000 / area
        economic_payload = {
            "area_m2": area, "cycles_per_year": 1, "mode": mode,
            "initial_capex_krw": capital, "horizon_years": horizon, "discount_rate": rate,
            "replacements_krw": replacements,
            "benchmark": {
                "period_basis": f"{start.isoformat()}~{end.isoformat()} 대상 시설 연간예산 / 1작기",
                "yield_kg_per_1000m2": q * factor, "farmgate_price_krw_per_kg": p,
                "operating_cost_krw_per_1000m2": (cash_cost + costs["depreciation_krw"]) * factor,
                "depreciation_krw_per_1000m2": costs["depreciation_krw"] * factor,
                "family_labor_cost_krw_per_1000m2": costs["family_labor_krw"] * factor,
            },
            "scenarios": [{"name": name, "yield_multiplier": 1, "price_multiplier": 1, "cash_cost_multiplier": 1}],
        }
        if mode == "retrofit":
            economic_payload["baseline"] = {
                "annual_cash_flow_krw": baseline_cash, "annual_income_krw": baseline_income,
                "replacements_krw": baseline_replacements,
            }
        calculated = evaluate_plan(economic_payload)
        item = calculated["scenarios"][0]
        item["assumptions"] = dict(scenario)
        item["revenue_basis"] = "facility_sales_allocation_times_predicted_shipment"
        margin = p - variable
        repayment = (capital + sum(replacements.values()) - sum(baseline_replacements.values())) / horizon
        required = None if margin <= 0 else max(0.0, (fixed + baseline_cash + repayment) / margin)
        item.update({
            "annual_fixed_cash_cost_krw": fixed, "variable_cash_cost_krw_per_kg": variable,
            "required_annual_yield_for_horizon_payback_kg": required,
            "additional_yield_required_kg": None if required is None else max(0.0, required - q),
            "operating_break_even_yield_kg": None if margin <= 0 else fixed / margin,
            "full_cost_break_even_price_krw_per_kg": None if q == 0 else (cash_cost + costs["depreciation_krw"] + costs["family_labor_krw"]) / q,
            "yield_headroom_before_cash_loss_kg": None if margin <= 0 else q - fixed / margin,
        })
        scenario_results.append(item)
        if name == "기준":
            output = calculated
    assert output is not None
    output["scenarios"] = scenario_results
    counts = dict(Counter(row["source_kind"] for row in ledger))
    output.update({
        "target_context": target,
        "model_connection": {"prediction": deepcopy(prediction), "cost_basis": "facility_bound_itemized_annual_budget",
                             "income_accuracy_validated": False, "period_assumption": "one_recorded_cycle_per_year"},
        "budget": {"weighted_price_krw_per_kg": price, **costs, "baseline": baseline_budget},
        "evidence_ledger": ledger,
        "evidence_summary": {"counts_by_kind": counts, "external_reference_used": bool(counts.get("external_reference")),
                             "documents_independently_verified": False},
        "quality": {"facility_period_binding_checked": True, "income_accuracy_validated": False,
                    "equipment_effect_validated": False, "source_target_period_confirmed": prediction.get("target_period_confirmed") is True,
                    "model_warnings": list(prediction.get("warnings", []))},
        "interpretation": "대상 시설에 입력한 판매계획·비용·견적 조건에 따른 전망 계산입니다. 실제 성과나 설비 도입의 인과효과를 검증한 결과는 아닙니다.",
        "period_note": "연간 운영비는 비재배기간까지 포함합니다. 한 작기의 예측을 연 1회 적용하며, 여러 해에는 같은 연간 계획을 반복하는 가정입니다.",
        "sensitivity_note": "시나리오 배율은 사용자가 정한 변화폭이며 신뢰구간·발생확률이 아닙니다. 개량 비교의 기존 유지안은 고정되어 있습니다.",
    })
    return output
