// Portable fitted tree equations. No requests, storage, or farm records.
const categorical = ['crop', 'variety', 'region', 'district', 'facility_type'];
const numeric = ['planting_year', 'planting_month', 'area_m2'];
const units = {shipment: 'kg_per_recorded_cycle', revenue: 'krw_per_recorded_cycle'};

function queryValues(query) {
  const result = Object.fromEntries(categorical.map(name => [name, String(query[name] ?? '__missing__')]));
  for (const name of numeric) {
    const value = query[name];
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) throw new Error(`Invalid ${name}`);
    result[name] = value;
  }
  if (!Number.isInteger(result.planting_month) || result.planting_month > 12 || !Number.isInteger(result.planting_year)) throw new Error('Invalid planting date');
  return result;
}

export function predictModel(bundle, rawQuery) {
  const query = queryValues(rawQuery);
  if (!bundle.support.crops.includes(query.crop)) return {status: 'unsupported_crop', prediction: null, target: bundle.target};
  const portable = bundle.portable;
  let density;
  if (portable.model === 'crop_area_median') {
    density = portable.medians[query.crop];
  } else {
    const encoded = categorical.flatMap((name, index) => portable.categories[index].map(value => Number(query[name] === value)));
    encoded.push(...numeric.map(name => Math.fround(query[name])));
    let sum = 0;
    for (const tree of portable.trees) {
      if (portable.model === 'catboost_log_density') {
        let leaf = 0;
        tree.splits.forEach((split, depth) => { if (encoded[split.feature] > split.border) leaf += 2 ** depth; });
        sum += tree.leaves[leaf];
      } else if (portable.model === 'xgboost_log_density') {
        let node = 0;
        while (tree.left_children[node] !== -1) node = encoded[tree.split_indices[node]] < tree.split_conditions[node] ? tree.left_children[node] : tree.right_children[node];
        sum += tree.split_conditions[node];
      } else throw new Error('Unknown fitted model');
    }
    density = Math.max(0, Math.expm1(sum * (portable.scale ?? 1) + portable.bias));
  }
  const value = density * query.area_m2;
  if (!Number.isFinite(value) || value < 0) throw new Error('Invalid prediction');
  const support = bundle.support.by_crop?.[query.crop] ?? bundle.support;
  const warnings = categorical.filter(name => !support.categories[name].includes(query[name])).map(name => `unseen_${name}`);
  if (support.locations && !(support.locations[query.region] ?? []).includes(query.district)) warnings.push('unseen_region_district_combination');
  if (query.area_m2 < support.area_min_m2 || query.area_m2 > support.area_max_m2) warnings.push('area_outside_training_range');
  if (query.planting_year > (bundle.support.latest_planting_year ?? 0)) warnings.push('future_year_not_prospectively_validated');
  return {status: 'predicted', target: bundle.target, unit: bundle.unit, prediction: value,
    model: portable.model, query, warnings, target_period_confirmed: false};
}

export function connectPrediction(payload, prediction, acknowledgePeriod) {
  if (acknowledgePeriod !== true) throw new Error('작기 예측을 연 1작기로 계산한다는 가정을 확인해주세요.');
  if (payload.cycles_per_year !== 1) throw new Error('농가 모델은 연 1작기 기준으로 연결합니다.');
  if (prediction.status !== 'predicted' || !Object.hasOwn(units, prediction.target) || prediction.unit !== units[prediction.target]) throw new Error('지원하는 예측 결과가 없습니다.');
  if (typeof prediction.prediction !== 'number' || !Number.isFinite(prediction.prediction) || prediction.prediction < 0) throw new Error('Invalid prediction');
  const area = payload.area_m2;
  if (!Number.isFinite(area) || area <= 0 || Math.abs(area - prediction.query.area_m2) > 1e-9 * Math.max(area, prediction.query.area_m2)) throw new Error('Prediction area differs from plan area');
  const result = structuredClone(payload);
  if (prediction.target === 'shipment') {
    delete result.annual_revenue_override_krw;
    result.benchmark.yield_kg_per_1000m2 = prediction.prediction / area * 1000;
  } else {
    result.annual_revenue_override_krw = prediction.prediction;
  }
  result.model_connection = {prediction, period_assumption: 'one_recorded_cycle_per_year',
    cost_basis: 'unchanged annual per-1000m2 reference', income_accuracy_validated: false};
  return result;
}
