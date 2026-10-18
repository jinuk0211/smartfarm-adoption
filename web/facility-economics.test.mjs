import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {COST_CATEGORIES, evaluateFacilityPlan, sameSnapshot} from './facility-economics.mjs';
import {predictModel} from './prediction.mjs';

function fixture() {
  const target = {plan_id: 'TEST_PLAN', facility_id: 'TEST_FACILITY', crop: '딸기', area_m2: 1000,
    cycle_start: '2026-09-01', cycle_end: '2027-05-31', financial_start: '2026-09-01', financial_end: '2027-08-31',
    variety: '설향', region: '경북', district: '고령', facility_type: '비닐온실'};
  const evidence = () => ({scope: structuredClone(target), source_kind: 'budget', source_ref: '자동 테스트의 가상 계획이며 실자료가 아님'});
  const costs = Object.keys(COST_CATEGORIES).map(category => ({...evidence(), category,
    amount_krw: ({seedlings: 1000, energy_water: 1000, hired_labor: 1000, packaging_transport: 1, depreciation: 2000, family_labor: 1000})[category] ?? 0,
    basis: category === 'packaging_transport' ? 'per_kg' : 'annual_total'}));
  return {
    target, evidence_target: structuredClone(target), mode: 'new',
    prediction: {status: 'predicted', target: 'shipment', unit: 'kg', prediction: 1000,
      query: {crop: '딸기', area_m2: 1000, planting_year: 2026, planting_month: 9, variety: '설향', region: '경북', district: '고령', facility_type: '비닐온실'},
      target_period_confirmed: false, warnings: ['future_year_not_prospectively_validated']},
    acknowledge_prediction_period: true, repeat_annual_plan: true,
    sales: [{...evidence(), label: '가상 계약', share: 1, net_price_krw_per_kg: 10, sale_start: '2026-12-01', sale_end: '2027-05-31'}],
    costs, investments: [{...evidence(), label: '가상 설치견적', amount_krw: 6000, coverage: '테스트용 전체 설치 가정, 실제 견적 아님'}],
    investment_scope_confirmed: true, horizon_years: 5, discount_rate: 0, replacements_krw: {},
    scenarios: [{name: '불리', yield_multiplier: .5, price_multiplier: 1, cash_cost_multiplier: 1},
      {name: '기준', yield_multiplier: 1, price_multiplier: 1, cash_cost_multiplier: 1}],
  };
}
const base = payload => evaluateFacilityPlan(payload).scenarios.find(row => row.name === '기준');
const close = (a, b) => assert.ok(Math.abs(a - b) <= Math.max(1e-8, Math.abs(b) * 1e-12), `${a} != ${b}`);

test('same facility itemized prices, costs, cash and income reproduce Python fixture amounts', () => {
  const payload = fixture(), result = evaluateFacilityPlan(payload), row = base(payload);
  assert.equal(row.annual_revenue_krw, 10000);
  assert.equal(row.annual_cash_operating_cost_krw, 4000);
  assert.equal(row.annual_income_after_family_labor_krw, 3000);
  assert.deepEqual(row.cash_flows_krw, [-6000, 6000, 6000, 6000, 6000, 6000]);
  assert.equal(row.payback_year, 1);
  assert.deepEqual(result.target_context, payload.target);
  assert.equal(result.quality.income_accuracy_validated, false);
});

test('sales mix and yield-dependent packaging use weighted prices and marginal cost break-even', () => {
  const payload = fixture();
  payload.sales[0].share = .75;
  payload.sales.push({...structuredClone(payload.sales[0]), label: '다른 판매채널', share: .25, net_price_krw_per_kg: 20});
  assert.equal(base(payload).annual_revenue_krw, 12500);
  const downside = evaluateFacilityPlan(fixture()).scenarios.find(row => row.name === '불리');
  assert.equal(downside.annual_cash_operating_cost_krw, 3500);
  assert.equal(downside.payback_year, 4);
  close(downside.required_annual_yield_for_horizon_payback_kg, (3000 + 6000 / 5) / 9);
  close(downside.operating_break_even_yield_kg, 3000 / 9);
});

test('changing facility, area, dates or model conditions never silently rebinds evidence', () => {
  for (const [field, value] of Object.entries({facility_id: 'OTHER', area_m2: 2000, crop: '토마토',
    cycle_end: '2027-06-01', variety: '다른품종', region: '경남', district: '다른시군', facility_type: '유리온실'})) {
    const payload = fixture(); payload.target[field] = value;
    assert.throws(() => evaluateFacilityPlan(payload), /변경/);
  }
  const payload = fixture();
  payload.target.variety = payload.evidence_target.variety = '다른품종';
  assert.throws(() => evaluateFacilityPlan(payload), /예측 variety/);
});

test('a single foreign scope or contradictory top-level row field is rejected', () => {
  for (const section of ['sales', 'costs', 'investments']) {
    for (const field of ['facility_id', 'area_m2', 'cycle_start', 'financial_start', 'variety']) {
      const payload = fixture(); payload[section][0].scope[field] = 'OTHER';
      assert.throws(() => evaluateFacilityPlan(payload), /계획과 다릅니다/);
    }
    const payload = fixture(); payload[section][0].facility_id = 'OTHER';
    assert.throws(() => evaluateFacilityPlan(payload), /항목이 연결 대상과 다릅니다/);
  }
});

test('missing and nonfinite money is rejected, explicit zero is retained, nine categories required', () => {
  for (const value of [null, undefined, '', ' ', true, NaN, Infinity, -1]) {
    const payload = fixture(); payload.costs[0].amount_krw = value;
    assert.throws(() => evaluateFacilityPlan(payload));
  }
  const payload = fixture(); payload.costs[0].amount_krw = 0;
  assert.equal(base(payload).annual_cash_operating_cost_krw, 3000);
  payload.costs.pop();
  assert.throws(() => evaluateFacilityPlan(payload), /필수 비용항목/);
});

function retrofitFixture() {
  const payload = fixture(), first = payload.sales[0];
  payload.mode = 'retrofit'; payload.replacements_krw = {'2': 400};
  payload.baseline = {scope: structuredClone(payload.target), source_kind: first.source_kind, source_ref: first.source_ref,
    yield_kg: 800, sales: structuredClone(payload.sales), costs: structuredClone(payload.costs), replacements_krw: {'2': 100}};
  return payload;
}

test('retrofit uses incremental cash and both replacement schedules from same target', () => {
  const payload = retrofitFixture(), row = base(payload);
  assert.equal(row.annual_incremental_cash_flow_before_replacements_krw, 1800);
  assert.deepEqual(row.cash_flows_krw, [-6000, 1800, 1500, 1800, 1800, 1800]);
  assert.equal(row.payback_year, 4);
  payload.baseline.scope.cycle_start = '2025-09-01';
  assert.throws(() => evaluateFacilityPlan(payload), /계획과 다릅니다/);
});

test('early recovery does not imply recovery after a later replacement', () => {
  const payload = fixture(); payload.replacements_krw = {'5': 40000};
  const row = base(payload);
  assert.equal(row.payback_year, 1);
  assert.equal(row.recovered_by_horizon, false);
  assert.equal(row.undiscounted_balance_krw, -16000);
});

test('invalid periods, sales shares, replacements and unstated conditions fail', () => {
  const changes = [
    payload => {payload.sales[0].share = .9;},
    payload => {payload.sales[0].sale_end = '2027-06-01';},
    payload => {payload.prediction.query.area_m2 = 2000;},
    payload => {payload.prediction.query.planting_month = 10;},
    payload => {payload.repeat_annual_plan = false;},
    payload => {payload.acknowledge_prediction_period = false;},
    payload => {payload.costs[0].source_ref = '';},
    payload => {payload.costs.push(structuredClone(payload.costs[0]));},
    payload => {payload.replacements_krw = null;},
    payload => {payload.replacements_krw = {'6': 1};},
    payload => {payload.target.financial_end = '2027-08-32';},
  ];
  for (const change of changes) {const payload = fixture(); change(payload); assert.throws(() => evaluateFacilityPlan(payload));}
});

test('unverified reference and quote remain declarations, not independently verified evidence', () => {
  const payload = fixture(); payload.costs[0].source_kind = 'external_reference'; payload.investments[0].source_kind = 'quote';
  const result = evaluateFacilityPlan(payload);
  assert.equal(result.evidence_summary.external_reference_used, true);
  assert.ok(result.evidence_ledger.every(row => row.document_verified === false));
  assert.equal(result.quality.equipment_effect_validated, false);
});

test('zero price and quantity do not create false finite break-even', () => {
  const payload = fixture(); payload.sales[0].net_price_krw_per_kg = 0;
  assert.equal(base(payload).required_annual_yield_for_horizon_payback_kg, null);
  assert.equal(base(payload).payback_year, null);
  payload.prediction.prediction = 0;
  assert.equal(base(payload).full_cost_break_even_price_krw_per_kg, null);
});

test('actual portable shipment unit and model conditions connect without changing source unit', () => {
  const bundle = JSON.parse(readFileSync(new URL('../reports/planning_models.json', import.meta.url))).models.shipment;
  const payload = fixture(), query = {...bundle.example_query, planting_year: 2026, planting_month: 9, area_m2: 1000};
  for (const key of ['variety', 'region', 'district', 'facility_type']) payload.target[key] = query[key];
  payload.evidence_target = structuredClone(payload.target);
  for (const section of ['sales', 'costs', 'investments']) for (const row of payload[section]) row.scope = structuredClone(payload.target);
  payload.prediction = predictModel(bundle, query);
  assert.equal(payload.prediction.unit, 'kg_per_recorded_cycle');
  const result = evaluateFacilityPlan(payload);
  assert.equal(result.model_connection.prediction.unit, 'kg_per_recorded_cycle');
  close(base(payload).annual_revenue_krw, payload.prediction.prediction * 10);
});

test('inputs are not mutated and snapshot equality ignores object key order', () => {
  const payload = fixture(), before = structuredClone(payload);
  evaluateFacilityPlan(payload);
  assert.deepEqual(payload, before);
  assert.equal(sameSnapshot({a: 1, b: {c: 2}}, {b: {c: 2}, a: 1}), true);
});

const project = fileURLToPath(new URL('../', import.meta.url));
const python = fileURLToPath(new URL('../.venv/Scripts/python.exe', import.meta.url));
test('all numeric result fields agree with current Python evaluator for new and retrofit cases', {skip: !existsSync(python)}, () => {
  for (const payload of [fixture(), retrofitFixture()]) {
    const native = JSON.parse(execFileSync(python, ['-c', 'import json,sys; from src.farm_economics import evaluate_facility_plan; print(json.dumps(evaluate_facility_plan(json.load(sys.stdin)),ensure_ascii=False))'],
      {cwd: project, input: JSON.stringify(payload), encoding: 'utf8', env: {...process.env, PYTHONUTF8: '1'}}));
    const actual = evaluateFacilityPlan(payload);
    assert.equal(actual.scenarios.length, native.scenarios.length);
    for (let i = 0; i < actual.scenarios.length; i++) {
      for (const [key, value] of Object.entries(native.scenarios[i])) {
        if (typeof value === 'number') close(actual.scenarios[i][key], value);
        else if (value === null || typeof value === 'boolean' || Array.isArray(value)) assert.deepEqual(actual.scenarios[i][key], value);
      }
    }
    assert.deepEqual(actual.evidence_ledger, native.evidence_ledger);
    assert.deepEqual(actual.budget, native.budget);
  }
});
