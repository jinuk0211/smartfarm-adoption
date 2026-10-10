// Browser port of src/economics.py, equipment_costs.py and risk_simulation.py.
// All monetary values are KRW. These calculations evaluate explicit assumptions.

function number(value, name, minimum = 0) {
  if (value === null || value === undefined || typeof value === 'boolean' ||
      (typeof value !== 'number' && typeof value !== 'string') ||
      (typeof value === 'string' && !value.trim())) {
    throw new Error(`${name} must be explicitly provided as a number`);
  }
  const result = Number(value);
  if (!Number.isFinite(result) || result < minimum) {
    throw new Error(`${name} must be finite and >= ${minimum}`);
  }
  return result;
}

function replacements(values, horizon) {
  if (values === null || typeof values !== 'object' || Array.isArray(values)) {
    throw new Error('replacements_krw must be a mapping of years to amounts');
  }
  const result = {};
  for (const [year, amount] of Object.entries(values)) {
    const yearInt = Number(year);
    if (!Number.isInteger(yearInt) || String(yearInt) !== year || yearInt < 1 || yearInt > horizon) {
      throw new Error('Replacement years must be whole years within the horizon');
    }
    result[yearInt] = number(amount, 'replacement cost');
  }
  return result;
}

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}

function cashFlowSummary(cashFlows, discountRate) {
  let cumulative = 0;
  let paybackYear = null;
  const cumulativeValues = cashFlows.map((value, year) => {
    cumulative += value;
    if (paybackYear === null && cumulative >= 0) paybackYear = year;
    return cumulative;
  });
  return {
    cash_flows_krw: cashFlows,
    cumulative_cash_flows_krw: cumulativeValues,
    payback_year: paybackYear,
    recovered_by_horizon: cumulative >= 0,
    npv_krw: sum(cashFlows.map((value, year) => value / (1 + discountRate) ** year)),
    undiscounted_balance_krw: cumulative,
  };
}

export function calculatePlan(payload) {
  const benchmark = payload.benchmark;
  const periodBasis = String(benchmark.period_basis ?? '').trim();
  if (!periodBasis) throw new Error('benchmark.period_basis is required');
  const area = number(payload.area_m2, 'area_m2');
  const cycles = number(payload.cycles_per_year, 'cycles_per_year');
  if (area === 0 || cycles === 0) throw new Error('area_m2 and cycles_per_year must be positive');
  const capital = number(payload.initial_capex_krw, 'initial_capex_krw');
  const horizon = number(payload.horizon_years, 'horizon_years', 1);
  if (!Number.isInteger(horizon)) throw new Error('horizon_years must be a whole number');
  const rate = number(payload.discount_rate === undefined ? 0 : payload.discount_rate, 'discount_rate');
  const replacementCosts = replacements(payload.replacements_krw === undefined ? {} : payload.replacements_krw, horizon);
  const mode = payload.mode === undefined ? 'new' : payload.mode;
  if (!['new', 'retrofit'].includes(mode)) throw new Error('mode must be new or retrofit');
  const scaling = area / 1000 * cycles;
  const yieldBase = number(benchmark.yield_kg_per_1000m2, 'benchmark yield') * scaling;
  const price = number(benchmark.farmgate_price_krw_per_kg, 'farmgate price');
  const expense = number(benchmark.operating_cost_krw_per_1000m2, 'operating cost') * scaling;
  const depreciation = number(benchmark.depreciation_krw_per_1000m2, 'depreciation') * scaling;
  if (depreciation > expense) throw new Error('Depreciation cannot exceed operating cost containing it');
  const cashCostBase = expense - depreciation;
  const familyLabor = benchmark.family_labor_cost_krw_per_1000m2 == null ? null :
    number(benchmark.family_labor_cost_krw_per_1000m2, 'family labor') * scaling;

  let baselineCash = 0;
  let baselineIncome = null;
  let baselineReplacements = {};
  if (mode === 'retrofit') {
    if (!payload.baseline) throw new Error('Retrofit requires an explicit existing-operation baseline');
    baselineCash = number(payload.baseline.annual_cash_flow_krw, 'baseline annual cash flow', -Infinity);
    if (payload.baseline.annual_income_krw != null) {
      baselineIncome = number(payload.baseline.annual_income_krw, 'baseline annual income', -Infinity);
    }
    baselineReplacements = replacements(payload.baseline.replacements_krw === undefined ? {} : payload.baseline.replacements_krw, horizon);
  }
  if (!Array.isArray(payload.scenarios) || !payload.scenarios.length) {
    throw new Error('At least one explicitly named scenario is required');
  }
  const outputs = payload.scenarios.map((scenario) => {
    const name = String(scenario.name ?? '').trim();
    if (!name) throw new Error('Each scenario needs a name');
    const quantity = yieldBase * number(scenario.yield_multiplier, 'yield_multiplier');
    const scenarioPrice = price * number(scenario.price_multiplier, 'price_multiplier');
    const cashCost = cashCostBase * number(scenario.cash_cost_multiplier, 'cash_cost_multiplier');
    const revenue = quantity * scenarioPrice;
    const cashSurplus = revenue - cashCost;
    const income = cashSurplus - depreciation;
    const incrementalCash = cashSurplus - baselineCash;
    const flows = [-capital, ...Array.from({length: horizon}, (_, index) => {
      const year = index + 1;
      return incrementalCash - (replacementCosts[year] ?? 0) + (baselineReplacements[year] ?? 0);
    })];
    const futureValue = sum(flows.slice(1));
    const discountedFuture = sum(flows.slice(1).map((value, index) => value / (1 + rate) ** (index + 1)));
    const annualRepayment = (capital + sum(Object.values(replacementCosts)) - sum(Object.values(baselineReplacements))) / horizon;
    const requiredRevenue = cashCost + baselineCash + annualRepayment;
    const requiredQuantity = scenarioPrice === 0 ? null : Math.max(0, requiredRevenue / scenarioPrice);
    return {
      name, assumptions: {...scenario}, annual_yield_kg: quantity,
      farmgate_price_krw_per_kg: scenarioPrice, annual_revenue_krw: revenue,
      annual_cash_operating_cost_krw: cashCost, annual_depreciation_krw: depreciation,
      annual_income_before_family_labor_krw: income,
      annual_family_labor_opportunity_cost_krw: familyLabor,
      annual_income_after_family_labor_krw: familyLabor === null ? null : income - familyLabor,
      annual_cash_surplus_before_replacements_krw: cashSurplus,
      annual_incremental_cash_flow_before_replacements_krw: incrementalCash,
      annual_incremental_income_krw: baselineIncome === null ? null : income - baselineIncome,
      maximum_capex_for_horizon_payback_krw: futureValue < 0 ? null : futureValue,
      maximum_capex_for_nonnegative_npv_krw: discountedFuture < 0 ? null : discountedFuture,
      required_annual_yield_for_horizon_payback_kg: requiredQuantity,
      additional_yield_required_kg: requiredQuantity === null ? null : Math.max(0, requiredQuantity - quantity),
      ...cashFlowSummary(flows, rate),
    };
  });
  return {
    mode, area_m2: area, period_basis: periodBasis, cycles_per_year: cycles,
    initial_capex_krw: capital, horizon_years: horizon, discount_rate: rate, scenarios: outputs,
    interpretation: 'Assumption scenarios, not confidence intervals or causal equipment effects',
    exclusions: ['tax', 'financing cash flows', 'grants', 'working-capital changes', 'terminal resale value'],
    cost_note: 'Operating cost includes depreciation; cash cost excludes it. Family labor is a separate opportunity cost.',
  };
}

export const evaluatePlan = calculatePlan;

function amount(value, name) {
  if (typeof value !== 'number') throw new Error(`${name} must be a number`);
  return number(value, name);
}

export function calculateEquipment(catalog, selections, installation = null, vat = null, otherCapex = null) {
  if (!Array.isArray(selections) || !selections.length) throw new Error('selections must contain at least one package');
  const seen = new Set();
  const lines = selections.map((selection) => {
    if (!selection || typeof selection !== 'object') throw new Error('Each selection must be a mapping');
    const id = selection.equipment_id;
    if (typeof id !== 'string' || !Object.hasOwn(catalog.packages, id)) throw new Error(`Unknown equipment_id: ${id}`);
    if (seen.has(id)) throw new Error('Duplicate equipment_id; use quantity instead');
    seen.add(id);
    const quantity = selection.quantity === undefined ? 1 : selection.quantity;
    if (!Number.isInteger(quantity) || quantity < 1) throw new Error('quantity must be a positive integer');
    const item = catalog.packages[id];
    const optionIds = selection.option_ids === undefined ? [] : selection.option_ids;
    if (!Array.isArray(optionIds) || optionIds.some((option) => typeof option !== 'string')) throw new Error('option_ids must be a list of option identifiers');
    if (new Set(optionIds).size !== optionIds.length) throw new Error('Duplicate option_id');
    const options = new Map(item.options.map((option) => [option.option_id, option]));
    if (optionIds.some((option) => !options.has(option))) throw new Error('Unknown option_id for selected package');
    const basePrice = amount(item.package_price_krw, 'package_price_krw');
    const optionsPrice = sum(optionIds.map((option) => amount(options.get(option).price_krw, 'option price')));
    return {
      equipment_id: id, name: item.name, quantity, option_ids: [...optionIds],
      package_price_krw: basePrice, options_price_per_package_krw: optionsPrice,
      line_total_krw: quantity * (basePrice + optionsPrice), source_url: item.source_url, checked_date: item.checked_date,
    };
  });
  const extras = {
    installation_krw: installation == null ? null : amount(installation, 'installation_krw'),
    additional_vat_krw: vat == null ? null : amount(vat, 'additional_vat_krw'),
    other_capex_krw: otherCapex == null ? null : amount(otherCapex, 'other_capex_krw'),
  };
  const unresolved = Object.keys(extras).filter((key) => extras[key] === null);
  const subtotal = sum(lines.map((line) => line.line_total_krw));
  return {
    lines, equipment_subtotal_krw: subtotal, ...extras,
    initial_capex_krw: unresolved.length ? null : subtotal + sum(Object.values(extras)),
    unresolved_cost_inputs: unresolved, status: unresolved.length ? 'incomplete_extra_costs' : 'planning_assumption',
    is_verified_quote: false,
    scope: '선택 장비와 명시한 설치비·추가 부가세·온실 등 기타비용을 합산한 가정. 실제 견적·호환성·생산성 효과는 확인되지 않음.',
    limitations: [...catalog.limitations],
  };
}

const OUTPUTS = ['annual_yield_kg', 'annual_revenue_krw', 'annual_cash_operating_cost_krw',
  'annual_income_before_family_labor_krw', 'annual_income_after_family_labor_krw',
  'npv_krw', 'undiscounted_balance_krw', 'required_annual_yield_for_horizon_payback_kg'];
const MULTIPLIERS = {yield: 'yield_multiplier', price: 'price_multiplier', cash_cost: 'cash_cost_multiplier'};

// Mulberry32 keeps browser runs reproducible; its draws differ from NumPy PCG64.
function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function quantile(sorted, probability) {
  const index = (sorted.length - 1) * probability;
  const lower = Math.floor(index);
  return sorted[lower] + (sorted[Math.ceil(index)] - sorted[lower]) * (index - lower);
}

export function simulateSensitivity(payload, {uncertainty = payload.sensitivity_half_widths,
  n_samples = 2000, seed = 42, scenario_index = 1} = {}) {
  const evaluated = calculatePlan(payload);
  if (!Number.isInteger(n_samples) || n_samples < 1 || n_samples > 20000) throw new Error('n_samples must be a whole number between 1 and 20000');
  if (!Number.isInteger(scenario_index) || scenario_index < 0 || scenario_index >= evaluated.scenarios.length) throw new Error('scenario_index must select an existing scenario');
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xFFFFFFFF) throw new Error('seed must be an unsigned 32-bit integer');
  if (!uncertainty || Object.keys(uncertainty).sort().join(',') !== Object.keys(MULTIPLIERS).sort().join(',')) {
    throw new Error('Explicit yield, price and cash_cost half-widths are required');
  }
  const random = seededRandom(seed);
  const widths = {};
  const factors = {};
  for (const key of Object.keys(MULTIPLIERS)) {
    const width = number(uncertainty[key], `uncertainty.${key}`);
    if (width > 1) throw new Error('Uncertainty half-widths must be between 0 and 1');
    widths[key] = width;
    factors[key] = Array.from({length: n_samples}, () => {
      if (width === 0) return 1;
      const uniform = random();
      return uniform < 0.5 ? 1 - width + width * Math.sqrt(2 * uniform) :
        1 + width - width * Math.sqrt(2 * (1 - uniform));
    });
  }
  const center = payload.scenarios[scenario_index];
  const draws = Array.from({length: n_samples}, (_, index) => ({
    ...center, name: `assumption_draw_${index + 1}`,
    ...Object.fromEntries(Object.entries(MULTIPLIERS).map(([key, field]) => [field, Number(center[field]) * factors[key][index]])),
  }));
  const samples = calculatePlan({...payload, scenarios: draws}).scenarios.map((row) => ({
    ...Object.fromEntries(OUTPUTS.map((key) => [key, row[key]])), payback_year: row.payback_year,
  }));
  const quantiles = Object.fromEntries(OUTPUTS.map((key) => {
    const values = samples.map((row) => row[key]).filter((value) => value !== null).sort((a, b) => a - b);
    return [key, values.length ? {p05: quantile(values, .05), p50: quantile(values, .5), p95: quantile(values, .95)} : null];
  }));
  return {
    deterministic: evaluated.scenarios[scenario_index], quantiles, samples,
    assumptions: {
      distribution: 'independent symmetric triangular multipliers centered at 1',
      relative_half_widths: widths, n_samples, seed, rng: 'Mulberry32 browser generator; not NumPy PCG64 sample identity',
      correlation: 'Independent yield/price/cash-cost factors; no estimated correlations',
      time_behavior: 'Each draw remains constant over the full horizon, not independent annual shocks',
      fixed_inputs: 'Capex, depreciation, baseline existing-operation cash flow, replacements and discount rate',
      interpretation: 'Assumption-distribution percentiles, NOT calibrated confidence intervals or success probabilities',
      bep_definition: 'Annual kg needed for undiscounted payback by the chosen horizon; family labor is separate',
      exclusions: evaluated.exclusions,
    },
  };
}

export const riskSimulation = simulateSensitivity;
