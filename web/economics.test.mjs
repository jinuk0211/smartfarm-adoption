import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {calculateEquipment, calculatePlan, simulateSensitivity} from './economics.mjs';

const fixture = JSON.parse(readFileSync(new URL('../reports/planning_demo_summary.json', import.meta.url)));
const catalog = JSON.parse(readFileSync(new URL('../data/processed/equipment_catalog.json', import.meta.url)));

function close(actual, expected, path = 'result') {
  if (typeof expected === 'number') {
    assert.ok(Math.abs(actual - expected) <= Math.max(1e-7, Math.abs(expected) * 1e-12), `${path}: ${actual} != ${expected}`);
  } else if (expected && typeof expected === 'object') {
    assert.deepEqual(Object.keys(actual), Object.keys(expected), path);
    for (const key of Object.keys(expected)) close(actual[key], expected[key], `${path}.${key}`);
  } else {
    assert.equal(actual, expected, path);
  }
}

function simplePlan() {
  return {
    benchmark: {yield_kg_per_1000m2: 1000, farmgate_price_krw_per_kg: 10,
      operating_cost_krw_per_1000m2: 6000, depreciation_krw_per_1000m2: 2000,
      family_labor_cost_krw_per_1000m2: 1000, period_basis: '1기작'},
    area_m2: 2000, cycles_per_year: 1, initial_capex_krw: 30000, horizon_years: 5, discount_rate: 0,
    scenarios: [{name: '명시적 가정', yield_multiplier: 1, price_multiplier: 1, cash_cost_multiplier: 1}],
  };
}

test('every scenario value matches archived Python output', () => {
  close(calculatePlan(fixture.inputs), fixture.results);
});

test('benchmark equipment includes selected options and explicit additional costs', () => {
  const result = calculateEquipment(catalog, [
    {equipment_id: '5126', quantity: 1, option_ids: []},
    {equipment_id: '6337', quantity: 1, option_ids: ['6337-option-1']},
  ], 5000000, 2957300, 80000000);
  assert.equal(result.equipment_subtotal_krw, 24573000);
  assert.equal(result.initial_capex_krw, 112530300);
  close(result.lines, fixture.inputs.capital_cost_basis.equipment.lines);
});

test('missing extras remain unresolved and package components are not added twice', () => {
  const result = calculateEquipment(catalog, [{equipment_id: '6337'}]);
  assert.equal(result.equipment_subtotal_krw, 3270000);
  assert.equal(result.initial_capex_krw, null);
  assert.deepEqual(result.unresolved_cost_inputs, ['installation_krw', 'additional_vat_krw', 'other_capex_krw']);
  assert.equal(calculateEquipment(catalog, [{equipment_id: '6688', quantity: 2, option_ids: ['6688-option-2']}], 1000000, 0, 0).initial_capex_krw, 31600000);
  for (const selections of [[], [null], [{equipment_id: 'missing'}], [{equipment_id: '6337'}, {equipment_id: '6337'}],
    [{equipment_id: '6337', quantity: true}], [{equipment_id: '6337', option_ids: ['6337-option-1', '6337-option-1']}],
    [{equipment_id: '6337', option_ids: ['6688-option-1']}]]) {
    assert.throws(() => calculateEquipment(catalog, selections, 0, 0, 0));
  }
});

test('area scaling preserves accounting, zero price has no division and missing labor stays unknown', () => {
  const input = simplePlan();
  let result = calculatePlan(input).scenarios[0];
  assert.equal(result.annual_yield_kg, 2000);
  assert.equal(result.annual_cash_operating_cost_krw, 8000);
  assert.equal(result.annual_income_after_family_labor_krw, 6000);
  assert.deepEqual(result.cash_flows_krw, [-30000, 12000, 12000, 12000, 12000, 12000]);
  assert.equal(result.payback_year, 3);
  input.scenarios[0].price_multiplier = 0;
  input.benchmark.family_labor_cost_krw_per_1000m2 = null;
  result = calculatePlan(input).scenarios[0];
  assert.equal(result.payback_year, null);
  assert.equal(result.maximum_capex_for_nonnegative_npv_krw, null);
  assert.equal(result.required_annual_yield_for_horizon_payback_kg, null);
  assert.equal(result.annual_income_after_family_labor_krw, null);
});

test('retrofit compares incremental cash and subtracts replacement differences', () => {
  const input = {...simplePlan(), mode: 'retrofit', baseline: {annual_cash_flow_krw: 10000, annual_income_krw: 7000, replacements_krw: {'2': 1000}}, replacements_krw: {'2': 4000}};
  const result = calculatePlan(input).scenarios[0];
  assert.deepEqual(result.cash_flows_krw, [-30000, 2000, -1000, 2000, 2000, 2000]);
  assert.equal(result.annual_incremental_income_krw, 1000);
  assert.equal(result.additional_yield_required_kg, 460);
  input.baseline.annual_cash_flow_krw = -1000;
  assert.equal(calculatePlan(input).scenarios[0].annual_incremental_cash_flow_before_replacements_krw, 13000);
});

test('discount and late replacement preserve first recovery separately from ending balance', () => {
  const input = {...simplePlan(), discount_rate: .1, replacements_krw: {'5': 100000}};
  const result = calculatePlan(input).scenarios[0];
  const expected = -30000 + [1, 2, 3, 4, 5].reduce((total, year) => total + 12000 / 1.1 ** year, 0) - 100000 / 1.1 ** 5;
  close(result.npv_krw, expected);
  assert.equal(result.payback_year, 3);
  assert.equal(result.recovered_by_horizon, false);
});

test('missing quotes, invalid costs and invalid replacement years are rejected', () => {
  for (const mutation of [
    (input) => { delete input.initial_capex_krw; },
    (input) => { input.initial_capex_krw = ''; },
    (input) => { input.mode = 'retrofit'; },
    (input) => { input.area_m2 = 0; },
    (input) => { input.benchmark.period_basis = ''; },
    (input) => { input.benchmark.depreciation_krw_per_1000m2 = 7000; },
    (input) => { input.replacements_krw = {'6': 100}; },
  ]) {
    const input = simplePlan(); mutation(input);
    assert.throws(() => calculatePlan(input));
  }
});

test('explicit null cannot silently choose a discount rate, mode or replacement assumption', () => {
  for (const field of ['discount_rate', 'mode', 'replacements_krw']) {
    assert.throws(() => calculatePlan({...fixture.inputs, [field]: null}), undefined, field);
  }
  assert.throws(() => calculatePlan({...simplePlan(), mode: 'retrofit',
    baseline: {annual_cash_flow_krw: 10000, replacements_krw: null}}), /replacements_krw/);
  close(calculatePlan(fixture.inputs).scenarios[1].npv_krw, 52565864.28515403);
});

test('omitted and undefined defaultable fields preserve the Python defaults', () => {
  const omitted = simplePlan();
  delete omitted.discount_rate;
  const result = calculatePlan(omitted);
  assert.equal(result.discount_rate, 0);
  assert.equal(result.mode, 'new');
  assert.deepEqual(result.scenarios[0].cash_flows_krw, [-30000, 12000, 12000, 12000, 12000, 12000]);
  close(calculatePlan({...omitted, discount_rate: undefined, mode: undefined, replacements_krw: undefined}), result);
  const retrofit = calculatePlan({...omitted, mode: 'retrofit', baseline: {annual_cash_flow_krw: 10000}});
  assert.deepEqual(retrofit.scenarios[0].cash_flows_krw, [-30000, 2000, 2000, 2000, 2000, 2000]);
});

test('explicit null equipment quantity or options are rejected; omitted values select one base package', () => {
  for (const field of ['quantity', 'option_ids']) {
    assert.throws(() => calculateEquipment(catalog, [{equipment_id: '6337', [field]: null}], 0, 0, 0), undefined, field);
  }
  const omitted = calculateEquipment(catalog, [{equipment_id: '6337'}], 0, 0, 0);
  assert.equal(omitted.initial_capex_krw, 3270000);
  assert.equal(omitted.lines[0].quantity, 1);
  assert.deepEqual(omitted.lines[0].option_ids, []);
  close(calculateEquipment(catalog, [{equipment_id: '6337', quantity: undefined, option_ids: undefined}], 0, 0, 0), omitted);
});

test('sensitivity is deterministic, bounded, centered on selected scenario and keeps assumptions explicit', () => {
  const options = {uncertainty: {yield: .1, price: .2, cash_cost: .1}, seed: 42, n_samples: 2000, scenario_index: 1};
  const result = simulateSensitivity(fixture.inputs, options);
  assert.deepEqual(result, simulateSensitivity(fixture.inputs, options));
  assert.equal(result.samples.length, 2000);
  assert.equal(result.deterministic.annual_yield_kg, 3344.5);
  assert.ok(result.samples.every((row) => row.annual_yield_kg >= 3344.5 * .9 && row.annual_yield_kg <= 3344.5 * 1.1));
  assert.ok(result.quantiles.npv_krw.p05 <= result.quantiles.npv_krw.p50 && result.quantiles.npv_krw.p50 <= result.quantiles.npv_krw.p95);
  assert.match(result.assumptions.interpretation, /NOT calibrated/);
  assert.match(result.assumptions.rng, /Mulberry32/);
  const zero = simulateSensitivity(fixture.inputs, {...options, n_samples: 3, uncertainty: {yield: 0, price: 0, cash_cost: 0}});
  assert.equal(zero.quantiles.npv_krw.p05, result.deterministic.npv_krw);
  assert.equal(zero.quantiles.npv_krw.p95, result.deterministic.npv_krw);
});
