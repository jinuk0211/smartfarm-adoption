import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {predictModel, connectPrediction} from './prediction.mjs';
import {calculatePlan, simulateSensitivity} from './economics.mjs';

const load = name => JSON.parse(readFileSync(new URL(`../reports/${name}.json`, import.meta.url), 'utf8'));
const models = load('planning_models').models;
const nativeChecks = load('planning_inference_checks');
const summary = load('planning_validation_summary');
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) <= Math.max(.1, Math.abs(expected) * 2e-6), `${actual} differs from ${expected}`);

test('actual exported models match native CatBoost/XGBoost/baseline inference checks', () => {
  assert.equal(nativeChecks.length, 10);
  for (const check of nativeChecks) close(predictModel(models[check.target], check.query).prediction, check.expected_native_prediction);
});

test('Python and browser forecast-to-economics agree for shipment and revenue', () => {
  for (const example of summary.examples) {
    const predicted = predictModel(models[example.target], example.inputs.model_connection.prediction.query);
    const inputs = connectPrediction(example.inputs, predicted, true);
    const result = calculatePlan(inputs);
    for (let i = 0; i < result.scenarios.length; i++) {
      const actual = result.scenarios[i], expected = example.results.scenarios[i];
      for (const name of ['annual_yield_kg', 'annual_revenue_krw', 'annual_cash_operating_cost_krw',
        'annual_income_after_family_labor_krw', 'npv_krw', 'required_annual_yield_for_horizon_payback_kg']) close(actual[name], expected[name]);
      assert.equal(actual.payback_year, expected.payback_year);
      assert.equal(actual.revenue_basis, expected.revenue_basis);
    }
  }
});

test('revenue-to-shipment switch clears stale revenue and applies area only once', () => {
  const input = structuredClone(summary.examples[0].inputs);
  const revenue = predictModel(models.revenue, models.revenue.example_query);
  const shipment = predictModel(models.shipment, models.shipment.example_query);
  const bridged = connectPrediction(connectPrediction(input, revenue, true), shipment, true);
  assert.equal(bridged.annual_revenue_override_krw, undefined);
  close(calculatePlan(bridged).scenarios[1].annual_revenue_krw, shipment.prediction * input.benchmark.farmgate_price_krw_per_kg);
});

test('unknown crop, malformed dates, and unconfirmed annual period are rejected', () => {
  const bundle = models.shipment, query = bundle.example_query;
  assert.equal(predictModel(bundle, {...query, crop: '바나나'}).status, 'unsupported_crop');
  for (const planting_month of [0, 13, 1.5, null, true]) assert.throws(() => predictModel(bundle, {...query, planting_month}));
  const prediction = predictModel(bundle, query);
  assert.throws(() => connectPrediction(summary.examples[0].inputs, prediction, false));
  assert.throws(() => connectPrediction({...summary.examples[0].inputs, cycles_per_year: 2}, prediction, true));
});

test('zero-width sensitivity equals each connected prediction plan', () => {
  for (const example of summary.examples) {
    const result = simulateSensitivity(example.inputs, {uncertainty: {yield: 0, price: 0, cash_cost: 0}, n_samples: 10, seed: 42, scenario_index: 1});
    close(result.quantiles.annual_revenue_krw.p50, example.results.scenarios[1].annual_revenue_krw);
    close(result.quantiles.npv_krw.p50, example.results.scenarios[1].npv_krw);
  }
});
