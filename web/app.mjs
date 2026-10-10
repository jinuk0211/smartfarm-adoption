import { calculatePlan, calculateEquipment, simulateSensitivity } from './economics.mjs';

const byId = (id) => document.getElementById(id);
const form = byId('planning-form');
const fields = {
  area: 'area_m2', cycles: 'cycles_per_year', horizon: 'horizon_years',
};
const benchmarkFields = {
  yield: 'yield_kg_per_1000m2', price: 'farmgate_price_krw_per_kg',
  operating: 'operating_cost_krw_per_1000m2', depreciation: 'depreciation_krw_per_1000m2',
  labor: 'family_labor_cost_krw_per_1000m2',
};
const state = { demo: null, catalog: null, inputs: null, result: null, equipment: null, sensitivity: null };
const number = (value, digits = 0) => Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits });
const money = (value) => `${number(value / 10000)}만원`;
const exactMoney = (value) => `${number(value)}원`;
const compactMoney = (value) => Math.abs(value) >= 100000000 ? `${number(value / 100000000, 2)}억원` : money(value);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const setText = (id, value) => { byId(id).textContent = value; };
const readNumber = (id) => byId(id).valueAsNumber;

async function loadJson(name) {
  const response = await fetch(`/data/${name}.json`);
  if (!response.ok) throw new Error(`${name} could not be loaded`);
  return response.json();
}

function renderEquipment() {
  byId('equipment-list').innerHTML = Object.values(state.catalog.packages).map((item) => `
    <div class="equipment-item">
      <div class="equipment-heading">
        <div><h4>${escapeHtml(item.name)}</h4><p>묶음 ${exactMoney(item.package_price_krw)}</p></div>
        <label class="quantity-label" for="qty-${escapeHtml(item.equipment_id)}">묶음 수량<input type="number" id="qty-${escapeHtml(item.equipment_id)}" data-equipment-id="${escapeHtml(item.equipment_id)}" min="0" max="1000" step="1" value="0" required aria-label="${escapeHtml(item.name)} 묶음 수량"></label>
      </div>
      <div class="equipment-options">${item.options.map((option) => `<label><input type="checkbox" data-equipment-option="${escapeHtml(item.equipment_id)}" value="${escapeHtml(option.option_id)}">${escapeHtml(option.name)} <span>+${exactMoney(option.price_krw)} / 묶음</span></label>`).join('')}</div>
    </div>`).join('');
}

function selections() {
  return Object.keys(state.catalog.packages).map((id) => ({
    equipment_id: id,
    quantity: readNumber(`qty-${id}`),
    option_ids: Array.from(form.querySelectorAll(`[data-equipment-option="${id}"]:checked`), (input) => input.value),
  })).filter((item) => item.quantity > 0);
}

function validateCrossFields() {
  byId('depreciation').setCustomValidity(readNumber('depreciation') > readNumber('operating') ? '감가상각비는 이를 포함하는 운영비 합계보다 클 수 없어요.' : '');
  const firstQuantity = form.querySelector('[data-equipment-id]');
  if (firstQuantity) firstQuantity.setCustomValidity(selections().length ? '' : '설비 묶음을 한 종류 이상 선택해주세요. 수량은 1 이상이어야 해요.');
}

function buildInputs() {
  const inputs = structuredClone(state.demo.inputs);
  for (const [id, key] of Object.entries(fields)) inputs[key] = readNumber(id);
  for (const [id, key] of Object.entries(benchmarkFields)) inputs.benchmark[key] = readNumber(id);
  inputs.discount_rate = readNumber('discount') / 100;
  inputs.mode = 'new';
  inputs.replacements_krw = {};
  const equipment = calculateEquipment(state.catalog, selections(), readNumber('installation'), readNumber('vat'), readNumber('other-capex'));
  inputs.initial_capex_krw = equipment.initial_capex_krw;
  inputs.capital_cost_basis = { equipment, other_capex_krw: equipment.other_capex_krw, total_initial_capex_krw: equipment.initial_capex_krw };
  inputs.reference = {
    ...state.demo.inputs.reference,
    yield_mode: '공개 조사자료 참고 + 사용자 가정',
    model_prediction: undefined,
    calculation_scope: 'Browser-local assumption calculator; no individual farm prediction or causal equipment effect',
    note: '입력값은 사용자가 바꿀 수 있습니다. 원자료 출처는 최초 참고 조건을 설명합니다.',
  };
  return { inputs, equipment };
}

function paybackText(scenario, horizon) {
  if (scenario.payback_year === null) return `${horizon}년 내 미회수`;
  if (scenario.payback_year === 0) return '초기 투자 0원';
  return `${scenario.payback_year}년째`;
}

function renderCashflow(result) {
  const width = 1100; const height = 325;
  const padding = { left: 93, right: 30, top: 28, bottom: 45 };
  const values = result.scenarios.flatMap((scenario) => scenario.cumulative_cash_flows_krw);
  const low = Math.min(0, ...values); const high = Math.max(0, ...values);
  const extent = Math.max(10000, high - low);
  const min = low - extent * .06; const max = high + extent * .08;
  const x = (year) => padding.left + year / result.horizon_years * (width - padding.left - padding.right);
  const y = (value) => padding.top + (max - value) / (max - min) * (height - padding.top - padding.bottom);
  const ticks = Array.from({ length: 5 }, (_, i) => low + (high - low) * i / 4);
  if (low === high) ticks.splice(0, ticks.length, 0);
  const yearStep = Math.max(1, Math.ceil(result.horizon_years / 10));
  const years = Array.from({ length: Math.floor(result.horizon_years / yearStep) + 1 }, (_, i) => i * yearStep);
  if (!years.includes(result.horizon_years)) years.push(result.horizon_years);
  const colors = ['#b6503d', '#204e3d', '#879b52'];
  const lines = result.scenarios.map((scenario, index) => `<polyline fill="none" stroke="${colors[index]}" stroke-width="${index === 1 ? 4 : 3}" stroke-linejoin="round" ${index === 0 ? 'stroke-dasharray="7 5"' : ''} points="${scenario.cumulative_cash_flows_krw.map((value, year) => `${x(year)},${y(value)}`).join(' ')}"/><circle cx="${x(result.horizon_years)}" cy="${y(scenario.undiscounted_balance_krw)}" r="4" fill="${colors[index]}"/>`).join('');
  const description = result.scenarios.map((scenario) => `${scenario.name}: ${result.horizon_years}년 후 누적 ${exactMoney(scenario.undiscounted_balance_krw)}, ${paybackText(scenario, result.horizon_years)}`).join('. ');
  byId('cashflow-chart').innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="cashflow-title cashflow-description"><title id="cashflow-title">세 시나리오의 누적 현금흐름</title><desc id="cashflow-description">${escapeHtml(description)}</desc><text x="12" y="16" fill="#66766c" font-size="12">단위: 만원</text>${ticks.map((tick) => `<line x1="${padding.left}" x2="${width - padding.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#e3e8de"/><text x="${padding.left - 12}" y="${y(tick) + 4}" text-anchor="end" fill="#66766c" font-size="13">${number(tick / 10000)}</text>`).join('')}<line x1="${padding.left}" x2="${width - padding.right}" y1="${y(0)}" y2="${y(0)}" stroke="#9cad99" stroke-width="1.5"/>${years.map((year) => `<text x="${x(year)}" y="${height - 15}" text-anchor="middle" fill="#66766c" font-size="13">${year}년</text>`).join('')}${lines}</svg>`;
}

function renderResults() {
  const { result, inputs } = state;
  const base = result.scenarios[1];
  const horizon = result.horizon_years;
  setText('result-basis', `딸기 · ${number(inputs.area_m2)}㎡ · 연 ${number(inputs.cycles_per_year)}작기`);
  setText('result-income', money(base.annual_income_after_family_labor_krw));
  byId('result-income').title = exactMoney(base.annual_income_after_family_labor_krw);
  setText('result-capex', compactMoney(inputs.initial_capex_krw));
  byId('result-capex').title = exactMoney(inputs.initial_capex_krw);
  setText('result-payback', paybackText(base, horizon));
  setText('result-yield', `${number(base.annual_yield_kg, 1)} kg`);
  setText('result-revenue', exactMoney(base.annual_revenue_krw));
  setText('result-operating', exactMoney(base.annual_cash_operating_cost_krw + base.annual_depreciation_krw));
  setText('result-labor', exactMoney(base.annual_family_labor_opportunity_cost_krw));
  setText('result-cash', money(base.annual_cash_surplus_before_replacements_krw));
  setText('capex-summary', compactMoney(inputs.initial_capex_krw));
  const descriptions = ['수확 −10% · 가격 −20% · 현금 운영비 +10%', '입력 조건 그대로', '수확 +10% · 가격 +20% · 현금 운영비 −10%'];
  byId('scenario-rows').innerHTML = result.scenarios.map((scenario, index) => `<tr class="${index === 1 ? 'base-row' : ''}"><td><span class="scenario-name">${escapeHtml(scenario.name)}</span><span class="scenario-assumption">${descriptions[index]}</span></td><td class="${scenario.annual_income_after_family_labor_krw < 0 ? 'negative' : ''}" title="${exactMoney(scenario.annual_income_after_family_labor_krw)}">${money(scenario.annual_income_after_family_labor_krw)}</td><td>${money(scenario.annual_cash_surplus_before_replacements_krw)}</td><td class="${scenario.npv_krw < 0 ? 'negative' : ''}" title="${exactMoney(scenario.npv_krw)}">${money(scenario.npv_krw)}</td><td>${paybackText(scenario, horizon)}</td></tr>`).join('');
  const adverse = result.scenarios[0];
  setText('adverse-note', adverse.undiscounted_balance_krw < 0
    ? `불리한 조건에서는 ${horizon}년이 지나도 투자금 ${money(Math.abs(adverse.undiscounted_balance_krw))}이 회수되지 않습니다. 감당할 수 있는 범위를 함께 살펴보세요.`
    : `이 입력 조건에서 불리 시나리오도 ${paybackText(adverse, horizon)}에 투자금을 회수합니다. 가정 밖의 가격·비용 변화는 별도로 확인해야 합니다.`);
  renderCashflow(result);
  byId('download-result').disabled = false;
  byId('run-sensitivity').disabled = false;
  byId('sensitivity-result').replaceChildren();
  state.sensitivity = null;
  setText('input-status', '아래 결과에 현재 입력 조건을 반영했어요.');
  byId('input-status').classList.remove('changed');
  byId('results').setAttribute('aria-label', `계산 결과. 연간 소득 ${money(base.annual_income_after_family_labor_krw)}, 투자금 회수 ${paybackText(base, horizon)}`);
}

function calculate(scroll = false) {
  validateCrossFields();
  if (!form.reportValidity()) return;
  try {
    const { inputs, equipment } = buildInputs();
    const result = calculatePlan(inputs);
    Object.assign(state, { inputs, equipment, result });
    renderResults();
    if (scroll) {
      byId('results').focus({ preventScroll: true });
      byId('results').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    }
  } catch (error) {
    setText('input-status', `계산할 수 없는 입력값이 있어요. 금액과 수량을 확인해주세요. (${error.message})`);
    byId('input-status').classList.add('changed');
  }
}

function resetExample() {
  const { inputs } = state.demo;
  for (const [id, key] of Object.entries(fields)) byId(id).value = inputs[key];
  for (const [id, key] of Object.entries(benchmarkFields)) byId(id).value = inputs.benchmark[key];
  byId('discount').value = inputs.discount_rate * 100;
  const capital = inputs.capital_cost_basis;
  byId('installation').value = capital.equipment.installation_krw;
  byId('vat').value = capital.equipment.additional_vat_krw;
  byId('other-capex').value = capital.other_capex_krw;
  for (const input of form.querySelectorAll('[data-equipment-id]')) input.value = 0;
  for (const input of form.querySelectorAll('[data-equipment-option]')) input.checked = false;
  for (const line of capital.equipment.lines) {
    byId(`qty-${line.equipment_id}`).value = line.quantity;
    for (const input of form.querySelectorAll(`[data-equipment-option="${line.equipment_id}"]`)) input.checked = line.option_ids.includes(input.value);
  }
  calculate();
}

function renderBars(targetId, items, digits = 2) {
  const largest = Math.max(...items.map((item) => item.value));
  const best = Math.min(...items.map((item) => item.value));
  byId(targetId).innerHTML = items.map((item) => `<div><div class="metric-bar-heading"><span>${escapeHtml(item.name)}</span><strong>${number(item.value, digits)} ${escapeHtml(item.unit)}</strong></div><div class="bar-track" aria-hidden="true"><div class="bar-fill ${item.value === best ? 'best' : ''}" style="width:${item.value / largest * 100}%"></div></div></div>`).join('');
}

function renderResearch(price, growth, references) {
  renderBars('price-metrics', [
    { name: '단순 기준모델', value: price.holdout_baseline.mae_krw_per_kg, unit: '원/kg' },
    { name: '2024년 선택 모델', value: price.holdout_selected.mae_krw_per_kg, unit: '원/kg' },
  ], 0);
  setText('price-study-scope', `단위를 kg으로 맞춘 ${number(price.observed_kg_rows)}개 관측 월, ${price.series_count}개 품목·품종·등급 시계열을 사용했습니다. 2025년 검증은 ${price.holdout_selected.evaluated_months}개 월입니다. 전체 평균은 품목별 가격 수준의 차이를 포함합니다.`);
  const names = { current_height: '현재 초장 유지 기준', catboost_growth: '생육만 사용 · CatBoost', catboost_growth_environment: '생육 + 환경 · CatBoost', xgboost_growth_environment: '생육 + 환경 · XGBoost' };
  renderBars('growth-metrics', growth.models.map((model) => ({ name: names[model.model] ?? model.model, value: model.mae_mm, unit: 'mm' })));
  byId('price-months').innerHTML = references.market_assumption.comparison.map((row) => `<tr><th scope="row">${row.month}월</th><td>${number(row.actual_2025_krw_per_kg)}</td><td>${number(row.forecast_2026_krw_per_kg)}</td></tr>`).join('');
}

function downloadPlan() {
  const payload = {
    generated_at: new Date().toISOString(),
    scope: 'Public aggregate references and user assumptions; not a validated individual farm forecast',
    inputs: state.inputs, results: state.result,
    sensitivity: state.sensitivity ? { quantiles: state.sensitivity.quantiles, assumptions: state.sensitivity.assumptions } : null,
    caveats: ['가족노동비 차감 후 소득과 차감 전 현금흐름을 구분합니다.', '회수기간은 감가상각을 제외한 현금 기준입니다.', '실제 설비 견적·생산성 효과는 검증되지 않았습니다.', '세금·대출·보조금·설비 교체·잔존가치는 제외했습니다.'],
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `smartfarm-plan-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

form.addEventListener('submit', (event) => { event.preventDefault(); calculate(true); });
form.addEventListener('invalid', (event) => {
  for (let parent = event.target.parentElement; parent && parent !== form; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
}, true);
form.addEventListener('input', () => {
  validateCrossFields();
  setText('input-status', '입력값이 바뀌었어요. 계산 버튼을 눌러 결과를 갱신해주세요.');
  byId('input-status').classList.add('changed');
});
byId('reset-example').addEventListener('click', resetExample);
byId('download-result').addEventListener('click', downloadPlan);
byId('run-sensitivity').addEventListener('click', () => {
  try {
    state.sensitivity = simulateSensitivity(state.inputs, { uncertainty: { yield: .1, price: .2, cash_cost: .1 }, n_samples: 2000, seed: 42, scenario_index: 1 });
    const quantiles = state.sensitivity.quantiles.npv_krw;
    byId('sensitivity-result').innerHTML = `<div class="sensitivity-values"><div><span>순현재가치 · 5백분위</span><strong>${money(quantiles.p05)}</strong></div><div><span>순현재가치 · 50백분위</span><strong>${money(quantiles.p50)}</strong></div><div><span>순현재가치 · 95백분위</span><strong>${money(quantiles.p95)}</strong></div></div><p class="fine-print">마지막으로 계산한 농장 조건 기준 · ${state.inputs.horizon_years}년 · 할인율 ${number(state.inputs.discount_rate * 100, 2)}%</p>`;
  } catch {
    setText('sensitivity-result', '현재 조건으로 범위를 계산하지 못했어요. 농장 조건을 다시 계산해주세요.');
  }
});

try {
  const [demo, catalog, price, growth, references] = await Promise.all([
    loadJson('planning_demo_summary'), loadJson('equipment_catalog'), loadJson('price_forecast_metrics_summary'),
    loadJson('inseason_metrics_summary'), loadJson('planning_reference_scenarios'),
  ]);
  Object.assign(state, { demo, catalog });
  renderEquipment();
  byId('planning-inputs').disabled = false;
  byId('reset-example').disabled = false;
  resetExample();
  renderResearch(price, growth, references);
  byId('load-status').hidden = true;
} catch {
  byId('load-status').classList.add('error');
  setText('load-status', '참고자료를 불러오지 못했어요. 인터넷 연결을 확인하고 새로고침해주세요. 기획서 다운로드는 위 메뉴에서 이용할 수 있습니다.');
}
