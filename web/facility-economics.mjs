// Facility-bound counterpart of src/farm_economics.py. No average-cost fallback.
import {calculatePlan} from './economics.mjs';

export const COST_CATEGORIES = {
  seedlings: '종묘·종자', fertilizer_crop_protection: '비료·농약·재배자재',
  energy_water: '난방·전기·용수', hired_labor: '고용노동',
  packaging_transport: '포장·운송·판매 관련 지출', rent: '임차료',
  repairs_other: '수선·유지·기타 현금비용', depreciation: '감가상각',
  family_labor: '가족노동 기회비용',
};
const SOURCE_KINDS = new Set(['user_record', 'quote', 'budget', 'external_reference']);
const MODEL_TEXT_FIELDS = ['variety', 'region', 'district', 'facility_type'];

function text(value, name) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${name}: 내용을 입력해야 합니다`);
  return value.trim();
}

function number(value, name, positive = false) {
  if (value === null || value === undefined || typeof value === 'boolean' ||
      !['number', 'string'].includes(typeof value) || (typeof value === 'string' && !value.trim())) {
    throw new Error(`${name}: 미입력은 0원이 아닙니다`);
  }
  const result = Number(value);
  if (!Number.isFinite(result) || result < 0 || (positive && result === 0)) {
    throw new Error(`${name}: 유효한 ${positive ? '양수' : '0 이상의 수'}가 필요합니다`);
  }
  return result;
}

function date(value, name) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`${name}: YYYY-MM-DD 날짜가 필요합니다`);
  }
  const result = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(result.valueOf()) || result.toISOString().slice(0, 10) !== value) {
    throw new Error(`${name}: 존재하는 YYYY-MM-DD 날짜가 필요합니다`);
  }
  return result;
}

export function sameSnapshot(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const a = Object.keys(left).sort(), b = Object.keys(right).sort();
  return a.length === b.length && a.every((key, i) => key === b[i] && sameSnapshot(left[key], right[key]));
}

export function validateFacilityTarget(target) {
  for (const name of ['plan_id', 'facility_id', 'crop', ...MODEL_TEXT_FIELDS]) text(target?.[name], name);
  const area = number(target.area_m2, '대상 면적', true);
  const start = date(target.financial_start, '연간 시작일');
  const end = date(target.financial_end, '연간 종료일');
  if (![365, 366].includes((end - start) / 86400000 + 1)) {
    throw new Error('재무기간은 실제 날짜 기준 1년(365/366일)이어야 합니다');
  }
  const cycleStart = date(target.cycle_start, '작기 시작일');
  const cycleEnd = date(target.cycle_end, '작기 종료일');
  if (!(start <= cycleStart && cycleStart <= cycleEnd && cycleEnd <= end)) {
    throw new Error('한 작기의 시작·종료일이 연간 재무기간 안에 있어야 합니다');
  }
  return {area, start, end, cycleStart, cycleEnd};
}

function evidence(row, target, label, ledger) {
  if (!sameSnapshot(row.scope, target)) throw new Error(`${label}: 대상 시설·면적·품목·작기 또는 연간 적용기간이 계획과 다릅니다`);
  for (const [key, value] of Object.entries(target)) {
    if (Object.hasOwn(row, key) && !sameSnapshot(row[key], value)) throw new Error(`${label}: ${key} 항목이 연결 대상과 다릅니다`);
  }
  if (!SOURCE_KINDS.has(row.source_kind)) throw new Error(`${label}: 근거 종류를 지정해야 합니다`);
  ledger.push({label, source_kind: row.source_kind,
    source_ref: text(row.source_ref, `${label} 출처·계산근거`),
    scope: structuredClone(target), document_verified: false});
}

function sales(rows, target, ledger, prefix) {
  if (!Array.isArray(rows) || !rows.length) throw new Error(`${prefix}: 판매계획이 필요합니다`);
  let shareSum = 0, weightedPrice = 0;
  const start = date(target.cycle_start, '작기 시작일'), end = date(target.cycle_end, '작기 종료일');
  rows.forEach((row, index) => {
    const label = `${prefix} ${index + 1} ${text(row.label, '판매 경로·등급')}`;
    evidence(row, target, label, ledger);
    const share = number(row.share, `${label} 출하 배분율`);
    if (share > 1) throw new Error('출하 배분율은 0~1이어야 합니다');
    const price = number(row.net_price_krw_per_kg, `${label} 수취단가`);
    const saleStart = date(row.sale_start, '판매 시작일'), saleEnd = date(row.sale_end, '판매 종료일');
    if (!(start <= saleStart && saleStart <= saleEnd && saleEnd <= end)) throw new Error(`${label}: 판매기간이 대상 작기를 벗어납니다`);
    shareSum += share;
    weightedPrice += share * price;
  });
  if (Math.abs(shareSum - 1) > 1e-8) throw new Error(`${prefix}: 출하 배분율 합계가 100%여야 합니다`);
  return weightedPrice;
}

function costs(rows, target, ledger, prefix) {
  if (!Array.isArray(rows)) throw new Error(`${prefix}: 비용항목이 필요합니다`);
  const categories = rows.map(row => row.category);
  if (new Set(categories).size !== categories.length) throw new Error(`${prefix}: 중복 비용항목이 있습니다`);
  if (categories.length !== Object.keys(COST_CATEGORIES).length || categories.some(key => !Object.hasOwn(COST_CATEGORIES, key))) {
    throw new Error(`${prefix}: 필수 비용항목을 모두 입력하세요`);
  }
  const result = {fixed_cash_krw: 0, variable_cash_krw_per_kg: 0, depreciation_krw: 0, family_labor_krw: 0};
  for (const row of rows) {
    const label = `${prefix} ${COST_CATEGORIES[row.category]}`;
    evidence(row, target, label, ledger);
    const amount = number(row.amount_krw, label);
    if (!['annual_total', 'per_kg'].includes(row.basis)) throw new Error(`${label}: 연간 총액 또는 kg당 비용 기준이 필요합니다`);
    if (['depreciation', 'family_labor'].includes(row.category) && row.basis !== 'annual_total') {
      throw new Error('감가상각·가족노동은 연간 총액으로 입력해야 합니다');
    }
    if (row.category === 'depreciation') result.depreciation_krw = amount;
    else if (row.category === 'family_labor') result.family_labor_krw = amount;
    else if (row.basis === 'annual_total') result.fixed_cash_krw += amount;
    else result.variable_cash_krw_per_kg += amount;
  }
  return result;
}

function replacements(values, horizon) {
  if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('교체 비용은 연도별 금액이어야 합니다');
  return Object.fromEntries(Object.entries(values).map(([key, value]) => {
    const year = Number(key);
    if (!Number.isInteger(year) || String(year) !== key || year < 1 || year > horizon) throw new Error('교체 연도는 분석기간 내 양의 정수여야 합니다');
    return [key, number(value, '교체 비용')];
  }));
}

export function evaluateFacilityPlan(payload) {
  const target = structuredClone(payload.target ?? {});
  const {area, cycleStart} = validateFacilityTarget(target);
  if (!sameSnapshot(payload.evidence_target, target)) throw new Error('근거를 연결한 대상 시설·면적·품목·작기가 변경되었습니다. 적용 근거를 다시 확인하세요');
  if (payload.acknowledge_prediction_period !== true) throw new Error('학습 출하 기록의 작기 완결 여부가 미확인임을 포함해 1작기 적용 조건을 확인하세요');
  const prediction = payload.prediction ?? {};
  if (prediction.status !== 'predicted' || prediction.target !== 'shipment' || !['kg', 'kg_per_recorded_cycle'].includes(prediction.unit)) throw new Error('kg 단위 작기 출하량 예측이 필요합니다');
  const quantity = number(prediction.prediction, '예측 출하량');
  const query = prediction.query ?? {};
  if (query.crop !== target.crop || Math.abs(number(query.area_m2, '모델 입력 면적', true) - area) > 1e-9 * Math.max(query.area_m2, area)) throw new Error('예측 품목·면적이 대상 시설 계획과 다릅니다');
  if (query.planting_year !== cycleStart.getUTCFullYear() || query.planting_month !== cycleStart.getUTCMonth() + 1) throw new Error('예측 정식 연월이 대상 작기 시작일과 다릅니다');
  for (const key of MODEL_TEXT_FIELDS) if (query[key] !== target[key]) throw new Error(`예측 ${key}가 대상 시설 계획과 다릅니다`);
  const horizon = number(payload.horizon_years, '분석기간', true);
  if (!Number.isInteger(horizon)) throw new Error('분석기간은 정수 연도여야 합니다');
  if (horizon > 1 && payload.repeat_annual_plan !== true) throw new Error('여러 해에 같은 연간 운영계획을 적용하는 가정을 확인하세요');
  const rate = number(payload.discount_rate, '할인율');
  if (!['new', 'retrofit'].includes(payload.mode)) throw new Error('신규 또는 기존 시설 개량 구분이 필요합니다');
  const ledger = [], price = sales(payload.sales, target, ledger, '도입안 판매');
  const budget = costs(payload.costs, target, ledger, '도입안 비용');
  if (!Array.isArray(payload.investments) || !payload.investments.length || payload.investment_scope_confirmed !== true) throw new Error('설비·설치·추가 공사 비용과 포함/제외 범위를 확인해야 합니다');
  let capital = 0;
  for (const row of payload.investments) {
    const label = text(row.label, '투자 항목');
    evidence(row, target, label, ledger);
    text(row.coverage, '투자비 포함/제외 범위');
    capital += number(row.amount_krw, label);
  }
  const replacement = replacements(Object.hasOwn(payload, 'replacements_krw') ? payload.replacements_krw : {}, horizon);
  let baselineCash = 0, baselineIncome = null, baselineReplacements = {}, baselineBudget = null;
  if (payload.mode === 'retrofit') {
    const baseline = payload.baseline;
    if (!baseline) throw new Error('개량 비교에는 같은 시설·연도의 기존 유지안 판매·비용 내역이 필요합니다');
    evidence(baseline, target, '기존 유지안', ledger);
    const baseQuantity = number(baseline.yield_kg, '기존 유지안 출하량');
    const basePrice = sales(baseline.sales, target, ledger, '기존 유지안 판매');
    const baseCosts = costs(baseline.costs, target, ledger, '기존 유지안 비용');
    const cashCost = baseCosts.fixed_cash_krw + baseQuantity * baseCosts.variable_cash_krw_per_kg;
    baselineCash = baseQuantity * basePrice - cashCost;
    baselineIncome = baselineCash - baseCosts.depreciation_krw;
    baselineReplacements = replacements(Object.hasOwn(baseline, 'replacements_krw') ? baseline.replacements_krw : {}, horizon);
    baselineBudget = {yield_kg: baseQuantity, weighted_price_krw_per_kg: basePrice,
      cash_cost_krw: cashCost, cash_surplus_krw: baselineCash, ...baseCosts};
  }
  const scenarios = payload.scenarios ?? [];
  const names = scenarios.map(row => row.name);
  if (!names.includes('기준') || new Set(names).size !== names.length) throw new Error("중복 없는 시나리오와 '기준' 시나리오가 필요합니다");
  let output;
  const resultScenarios = scenarios.map(scenario => {
    const name = text(scenario.name, '시나리오 이름');
    const ym = number(scenario.yield_multiplier, '출하량 배율');
    const pm = number(scenario.price_multiplier, '가격 배율');
    const cm = number(scenario.cash_cost_multiplier, '현금비용 배율');
    if (name === '기준' && (ym !== 1 || pm !== 1 || cm !== 1)) throw new Error('기준 시나리오의 출하량·가격·현금비용 배율은 모두 1이어야 합니다');
    const q = quantity * ym, p = price * pm;
    const fixed = budget.fixed_cash_krw * cm, variable = budget.variable_cash_krw_per_kg * cm;
    const cashCost = fixed + q * variable, factor = 1000 / area;
    const economic = {
      area_m2: area, cycles_per_year: 1, mode: payload.mode, initial_capex_krw: capital,
      horizon_years: horizon, discount_rate: rate, replacements_krw: replacement,
      benchmark: {period_basis: `${target.financial_start}~${target.financial_end} 대상 시설 연간예산 / 1작기`,
        yield_kg_per_1000m2: q * factor, farmgate_price_krw_per_kg: p,
        operating_cost_krw_per_1000m2: (cashCost + budget.depreciation_krw) * factor,
        depreciation_krw_per_1000m2: budget.depreciation_krw * factor,
        family_labor_cost_krw_per_1000m2: budget.family_labor_krw * factor},
      scenarios: [{name, yield_multiplier: 1, price_multiplier: 1, cash_cost_multiplier: 1}],
    };
    if (payload.mode === 'retrofit') economic.baseline = {annual_cash_flow_krw: baselineCash, annual_income_krw: baselineIncome, replacements_krw: baselineReplacements};
    const calculated = calculatePlan(economic);
    const item = calculated.scenarios[0];
    if (name === '기준') output = calculated;
    const margin = p - variable;
    const sum = object => Object.values(object).reduce((total, value) => total + value, 0);
    const repayment = (capital + sum(replacement) - sum(baselineReplacements)) / horizon;
    const required = margin <= 0 ? null : Math.max(0, (fixed + baselineCash + repayment) / margin);
    return {...item, assumptions: {...scenario}, revenue_basis: 'facility_sales_allocation_times_predicted_shipment',
      annual_fixed_cash_cost_krw: fixed, variable_cash_cost_krw_per_kg: variable,
      required_annual_yield_for_horizon_payback_kg: required,
      additional_yield_required_kg: required === null ? null : Math.max(0, required - q),
      operating_break_even_yield_kg: margin <= 0 ? null : fixed / margin,
      full_cost_break_even_price_krw_per_kg: q === 0 ? null : (cashCost + budget.depreciation_krw + budget.family_labor_krw) / q,
      yield_headroom_before_cash_loss_kg: margin <= 0 ? null : q - fixed / margin};
  });
  const counts = {};
  ledger.forEach(row => { counts[row.source_kind] = (counts[row.source_kind] ?? 0) + 1; });
  return {...output, scenarios: resultScenarios, target_context: target,
    model_connection: {prediction: structuredClone(prediction), cost_basis: 'facility_bound_itemized_annual_budget',
      income_accuracy_validated: false, period_assumption: 'one_recorded_cycle_per_year'},
    budget: {weighted_price_krw_per_kg: price, ...budget, baseline: baselineBudget},
    evidence_ledger: ledger,
    evidence_summary: {counts_by_kind: counts, external_reference_used: !!counts.external_reference, documents_independently_verified: false},
    quality: {facility_period_binding_checked: true, income_accuracy_validated: false, equipment_effect_validated: false,
      source_target_period_confirmed: prediction.target_period_confirmed === true, model_warnings: [...(prediction.warnings ?? [])]},
    interpretation: '대상 시설에 입력한 판매계획·비용·견적 조건에 따른 전망 계산입니다. 실제 성과나 설비 도입의 인과효과를 검증한 결과는 아닙니다.',
    period_note: '연간 운영비는 비재배기간까지 포함합니다. 한 작기의 예측을 연 1회 적용하며, 여러 해에는 같은 연간 계획을 반복하는 가정입니다.',
    sensitivity_note: '시나리오 배율은 사용자가 정한 변화폭이며 신뢰구간·발생확률이 아닙니다. 개량 비교의 기존 유지안은 고정되어 있습니다.',
  };
}
