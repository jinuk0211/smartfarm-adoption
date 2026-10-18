import {COST_CATEGORIES, evaluateFacilityPlan, sameSnapshot, validateFacilityTarget} from './facility-economics.mjs';
import {predictModel} from './prediction.mjs';

const $ = id => document.getElementById(id);
const state = {model: null, modelHash: null, evidenceTarget: null, bound: false, result: null, payload: null, example: false};
const SOURCE_LABELS = {user_record: '내 시설 기록', quote: '해당 시설 견적·계약', budget: '내가 세운 예산', external_reference: '외부 참고자료 적용'};
const sourceOptions = '<option value="">근거 종류 선택</option>' + Object.entries(SOURCE_LABELS).map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const formatted = (value, digits = 0) => value === null ? '계산 불가' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: digits});
const money = value => value === null ? '계산 불가' : `${formatted(value)}원`;
const num = id => $(id).value.trim() === '' ? null : $(id).valueAsNumber;
const rowNum = (row, name) => {
  const field = row.querySelector(`[data-field="${name}"]`);
  return field.value.trim() === '' ? null : field.valueAsNumber;
};
const rowText = (row, name) => row.querySelector(`[data-field="${name}"]`).value.trim();
const textField = (name, label, type = 'text', extra = '') => `<label>${label}<input data-field="${name}" type="${type}" ${extra} required></label>`;
const sourceFields = `<label>근거 종류<select data-field="source_kind" required>${sourceOptions}</select></label><label class="full">출처·산출근거<input data-field="source_ref" required placeholder="문서 이름·일자 또는 계산식과 적용 이유"></label>`;

function entry(container, title, body, removable = true) {
  const element = document.createElement('div');
  element.className = 'entry-card';
  element.innerHTML = `<div class="entry-heading"><h3>${title}</h3>${removable ? '<button type="button" class="remove-row">삭제</button>' : ''}</div><div class="grid">${body}</div>`;
  if (removable) element.querySelector('.remove-row').addEventListener('click', () => {element.remove(); invalidateResult();});
  $(container).append(element);
  return element;
}

function addSale(container) {
  return entry(container, '판매 경로·등급', textField('label', '경로·등급 이름') +
    textField('share_percent', '예측 출하량 배분 (%)', 'number', 'min="0" max="100" step="any"') +
    textField('net_price_krw_per_kg', '농가 수취단가 (원/kg)', 'number', 'min="0" step="any"') +
    textField('sale_start', '판매 시작일', 'date') + textField('sale_end', '판매 종료일', 'date') + sourceFields);
}

function renderCosts(container) {
  $(container).replaceChildren();
  for (const [category, label] of Object.entries(COST_CATEGORIES)) {
    const fixed = ['depreciation', 'family_labor'].includes(category);
    const row = entry(container, label,
      textField('amount_krw', '금액 (원)', 'number', 'min="0" step="any"') +
      `<label>금액 기준<select data-field="basis"><option value="annual_total">시설 전체의 연간 총액</option>${fixed ? '' : '<option value="per_kg">출하량 1kg당 비용</option>'}</select></label>` + sourceFields, false);
    row.dataset.category = category;
  }
}

function addInvestment() {
  return entry('investment-rows', '투자 항목', textField('label', '견적·투자 항목 이름') +
    textField('amount_krw', '초기 투자금액 (원)', 'number', 'min="0" step="any"') +
    textField('coverage', '포함·제외 범위 (설치·공사·세금 등)') + sourceFields);
}

function addReplacement(container) {
  return entry(container, '교체 지출', textField('year', '몇 년차 말인가요?', 'number', 'min="1" max="50" step="1"') +
    textField('amount_krw', '해당 연도 총 교체비 (원)', 'number', 'min="0" step="any"') +
    textField('source_ref', '교체 대상·주기·금액의 근거'));
}

function readTarget() {
  return {plan_id: $('plan-id').value.trim(), facility_id: $('facility-id').value.trim(), crop: '딸기',
    area_m2: num('area-m2'), cycle_start: $('cycle-start').value, cycle_end: $('cycle-end').value,
    financial_start: $('financial-start').value, financial_end: $('financial-end').value,
    variety: $('variety').value, region: $('region').value, district: $('district').value, facility_type: $('facility-type').value};
}

function predictionFor(target) {
  const beginning = target.cycle_start.split('-').map(Number);
  return predictModel(state.model, {crop: target.crop, variety: target.variety, region: target.region,
    district: target.district, facility_type: target.facility_type, area_m2: target.area_m2,
    planting_year: beginning[0], planting_month: beginning[1]});
}

function fillOptions(id, values, selected = '') {
  $(id).replaceChildren(new Option('선택하세요', ''), ...values.map(value => new Option(value, value)));
  $(id).value = values.includes(selected) ? selected : '';
}

function updateDistrict() {
  const support = state.model.support.by_crop?.['딸기'] ?? state.model.support;
  fillOptions('district', support.locations?.[$('region').value] ?? [], $('district').value);
}

function showError(message) {
  $('form-error').textContent = message;
  $('form-error').hidden = false;
  $('form-error').scrollIntoView({block: 'center', behavior: 'smooth'});
}

function invalidateResult() {
  if (state.result) $('result-stale').hidden = false;
  $('download-result').disabled = true;
  $('form-error').hidden = true;
}

function updateMode() {
  const retrofit = $('mode').value === 'retrofit';
  $('baseline-section').hidden = !retrofit;
  $('baseline-inputs').disabled = !retrofit || !state.bound;
}

function invalidateBinding() {
  invalidateResult();
  if (!state.evidenceTarget) return;
  state.bound = false;
  $('budget-inputs').disabled = true;
  $('rebind-area').hidden = false;
  $('rebind-ack').checked = false;
  $('prediction-preview').hidden = true;
  $('binding-status').textContent = '대상 조건이 변경되어 근거 연결을 잠갔습니다. 판매·비용·견적을 검토한 뒤 다시 연결하세요.';
  updateMode();
}

function bindTarget() {
  try {
    for (const control of $('target-inputs').querySelectorAll('input,select')) {
      if (!control.reportValidity()) return false;
    }
    const target = readTarget();
    validateFacilityTarget(target);
    if (state.evidenceTarget && !sameSnapshot(state.evidenceTarget, target) && !$('rebind-ack').checked) {
      throw new Error('이전 입력을 새 대상에 적용하기 전에 판매·비용·견적을 다시 확인하고 재연결 확인란을 체크하세요.');
    }
    const predicted = predictionFor(target);
    if (predicted.status !== 'predicted') throw new Error('이 품목을 지원하는 출하량 모델이 없습니다.');
    state.evidenceTarget = structuredClone(target);
    state.bound = true;
    $('budget-inputs').disabled = false;
    $('rebind-area').hidden = true;
    $('binding-status').textContent = `${target.facility_id} · ${formatted(target.area_m2)}㎡ · ${target.financial_start}~${target.financial_end}에 아래 근거를 연결합니다.`;
    $('prediction-preview').innerHTML = `<span>이 조건의 기록 기반 출하량 예측</span><br><strong>${formatted(predicted.prediction, 1)} kg</strong><p>정식 ${target.cycle_start.slice(0, 7)} · 모델 ${escape(predicted.model)}. 이 수치만으로 수익이나 설비 효과가 검증되지는 않습니다.</p>${predicted.warnings.length ? `<p class="hint">입력 범위 주의: ${escape(predicted.warnings.join(', '))}</p>` : ''}`;
    $('prediction-preview').hidden = false;
    updateMode();
    invalidateResult();
    return true;
  } catch (error) {showError(error.message); return false;}
}

function recordEvidence(row) {
  return {scope: structuredClone(state.evidenceTarget), source_kind: rowText(row, 'source_kind'), source_ref: rowText(row, 'source_ref')};
}

function readSales(container) {
  return [...$(container).children].map(row => ({...recordEvidence(row), label: rowText(row, 'label'),
    share: rowNum(row, 'share_percent') === null ? null : rowNum(row, 'share_percent') / 100,
    net_price_krw_per_kg: rowNum(row, 'net_price_krw_per_kg'),
    sale_start: rowText(row, 'sale_start'), sale_end: rowText(row, 'sale_end')}));
}

function readCosts(container) {
  return [...$(container).children].map(row => ({...recordEvidence(row), category: row.dataset.category,
    amount_krw: rowNum(row, 'amount_krw'), basis: rowText(row, 'basis')}));
}

function readReplacements(container) {
  const amounts = {}, entries = [];
  for (const row of $(container).children) {
    const year = rowNum(row, 'year');
    if (year === null || !Number.isInteger(year) || year < 1) throw new Error('교체 연도를 양의 정수로 입력하세요.');
    if (Object.hasOwn(amounts, String(year))) throw new Error('같은 교체 연도는 총액 한 행으로 합쳐 입력하세요.');
    const source = rowText(row, 'source_ref');
    if (!source) throw new Error('교체계획의 근거를 입력하세요.');
    amounts[year] = rowNum(row, 'amount_krw');
    entries.push({year, amount_krw: amounts[year], source_ref: source, scope: structuredClone(state.evidenceTarget), document_verified: false});
  }
  return {amounts, entries};
}

function readScenarios() {
  const base = {name: '기준', yield_multiplier: 1, price_multiplier: 1, cash_cost_multiplier: 1};
  if (!$('use-sensitivity').checked) return [base];
  const widths = ['yield-change', 'price-change', 'cost-change'].map(id => {
    const value = num(id);
    if (value === null || !Number.isFinite(value) || value < 0 || value > 100) throw new Error('시나리오 변화폭을 각각 0~100%로 입력하세요.');
    return value / 100;
  });
  return [{name: '불리', yield_multiplier: 1 - widths[0], price_multiplier: 1 - widths[1], cash_cost_multiplier: 1 + widths[2]}, base,
    {name: '유리', yield_multiplier: 1 + widths[0], price_multiplier: 1 + widths[1], cash_cost_multiplier: 1 - widths[2]}];
}

function buildPayload() {
  const target = readTarget();
  if (!state.bound || !sameSnapshot(state.evidenceTarget, target)) throw new Error('시설·면적·기간의 연결을 먼저 확인하세요.');
  if (!$('replacement-confirmed').checked) throw new Error('도입안 교체계획이 입력되었는지 확인하세요.');
  const replacement = readReplacements('replacement-rows');
  const payload = {
    target, evidence_target: structuredClone(state.evidenceTarget), mode: $('mode').value,
    prediction: predictionFor(target), acknowledge_prediction_period: $('period-ack').checked,
    repeat_annual_plan: $('repeat-plan').checked,
    sales: readSales('sales-rows'), costs: readCosts('cost-rows'),
    investments: [...$('investment-rows').children].map(row => ({...recordEvidence(row),
      label: rowText(row, 'label'), amount_krw: rowNum(row, 'amount_krw'), coverage: rowText(row, 'coverage')})),
    investment_scope_confirmed: $('investment-confirmed').checked,
    horizon_years: num('horizon'), discount_rate: num('discount') === null ? null : num('discount') / 100,
    replacements_krw: replacement.amounts, replacement_schedule_notes: replacement.entries,
    scenarios: readScenarios(),
  };
  if (payload.mode === 'retrofit') {
    if (!$('baseline-replacement-confirmed').checked) throw new Error('기존 유지안의 교체계획도 확인하세요.');
    const baselineReplacement = readReplacements('baseline-replacement-rows');
    payload.baseline = {scope: structuredClone(state.evidenceTarget), source_kind: $('baseline-source-kind').value,
      source_ref: $('baseline-source-ref').value.trim(), yield_kg: num('baseline-yield'),
      sales: readSales('baseline-sales-rows'), costs: readCosts('baseline-cost-rows'),
      replacements_krw: baselineReplacement.amounts, replacement_schedule_notes: baselineReplacement.entries};
  }
  return payload;
}

function payback(row, horizon) {
  if (!row.recovered_by_horizon) return `${horizon}년 말 미회수${row.payback_year === null ? '' : ` (최초 ${row.payback_year}년차 회수 후 재적자)`}`;
  return row.payback_year === 0 ? '초기 투자 0원' : `${row.payback_year}년차 말`;
}

function renderResult(result) {
  const base = result.scenarios.find(row => row.name === '기준');
  $('result').hidden = false;
  $('result-stale').hidden = true;
  $('result-target').textContent = `${result.target_context.facility_id} · ${formatted(result.area_m2)}㎡ · ${result.target_context.financial_start}~${result.target_context.financial_end} · ${state.example ? '가상 예시' : '사용자 입력 근거'}`;
  const metric = (label, value, note, negative = false) => `<div class="metric${negative ? ' negative' : ''}"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`;
  $('result-metrics').innerHTML =
    metric('예측 출하량', `${formatted(base.annual_yield_kg, 1)} kg`, '기록 기반 예측을 연 1작기에 적용') +
    metric('계산 매출', money(base.annual_revenue_krw), '예측 kg × 판매배분 가중 수취단가') +
    metric('가족노동 차감 후 소득', money(base.annual_income_after_family_labor_krw), '현금비용·감가상각·가족노동 차감', base.annual_income_after_family_labor_krw < 0) +
    metric(result.mode === 'retrofit' ? '기존 유지안 대비 연간 증분 현금' : '연간 현금 잔여', money(base.annual_incremental_cash_flow_before_replacements_krw), '교체 지출 전 · 가족노동 기회비용 차감 전', base.annual_incremental_cash_flow_before_replacements_krw < 0) +
    metric('투자 회수 상태', escape(payback(base, result.horizon_years)), `초기 투자 ${money(result.initial_capex_krw)}`, !base.recovered_by_horizon) +
    metric(`${result.horizon_years}년 말 누적 현금`, money(base.undiscounted_balance_krw), '초기 투자와 연도별 교체 지출 반영', base.undiscounted_balance_krw < 0);
  $('result-meaning').textContent = `${result.interpretation} ${result.evidence_summary.external_reference_used ? '외부 참고자료를 적용한 항목이 있어 대상 시설의 실제 기록과 구분해야 합니다.' : '외부 평균 비용을 자동으로 대입하지 않았습니다.'}`;
  $('scenario-results').innerHTML = `<table><caption>명시한 가정의 비교 · 확률 또는 신뢰구간 아님</caption><thead><tr><th>시나리오</th><th>소득 (가족노동 후)</th><th>회수에 필요한 연간 출하량</th><th>부족 출하량</th><th>회수 상태</th><th>종료 누적 현금</th></tr></thead><tbody>${result.scenarios.map(row => `<tr><td>${escape(row.name)}<br><small>출하×${row.assumptions.yield_multiplier}, 가격×${row.assumptions.price_multiplier}, 현금비용×${row.assumptions.cash_cost_multiplier}</small></td><td>${money(row.annual_income_after_family_labor_krw)}</td><td>${row.required_annual_yield_for_horizon_payback_kg === null ? '계산 불가' : `${formatted(row.required_annual_yield_for_horizon_payback_kg, 1)} kg`}</td><td>${row.additional_yield_required_kg === null ? '계산 불가' : `${formatted(row.additional_yield_required_kg, 1)} kg`}</td><td>${escape(payback(row, result.horizon_years))}</td><td>${money(row.undiscounted_balance_krw)}</td></tr>`).join('')}</tbody></table>`;
  const lines = [
    ['판매배분으로 계산한 가중 수취단가', `${formatted(result.budget.weighted_price_krw_per_kg, 2)}원/kg`],
    ['연간 고정 현금비용', money(base.annual_fixed_cash_cost_krw)],
    ['출하량에 따라 변하는 비용', `${formatted(base.variable_cash_cost_krw_per_kg, 2)}원/kg × ${formatted(base.annual_yield_kg, 1)}kg`],
    ['연간 현금 운영비 합계', money(base.annual_cash_operating_cost_krw)],
    ['매출 − 현금 운영비 = 현금 잔여', money(base.annual_cash_surplus_before_replacements_krw)],
    ['별도 감가상각', money(base.annual_depreciation_krw)],
    ['별도 가족노동 기회비용', money(base.annual_family_labor_opportunity_cost_krw)],
    ['현금 운영비 손익분기 출하량', base.operating_break_even_yield_kg === null ? '계산 불가' : `${formatted(base.operating_break_even_yield_kg, 1)} kg`],
    ['감가상각·가족노동까지 충당하는 수취단가', base.full_cost_break_even_price_krw_per_kg === null ? '계산 불가' : `${formatted(base.full_cost_break_even_price_krw_per_kg, 2)}원/kg`],
    ['현금 손실 전까지 줄어들 수 있는 출하량', base.yield_headroom_before_cash_loss_kg === null ? '계산 불가' : `${formatted(base.yield_headroom_before_cash_loss_kg, 1)} kg`],
    ['선택 할인율의 순현재가치 (NPV)', money(base.npv_krw)],
  ];
  if (result.budget.baseline) lines.splice(5, 0, ['같은 시설의 기존 유지안 현금 잔여', money(result.budget.baseline.cash_surplus_krw)]);
  $('calculation-detail').innerHTML = lines.map(([label, value]) => `<div class="calculation-line"><span>${label}</span><strong>${value}</strong></div>`).join('') + `<p class="hint">회수에 필요한 출하량은 선택한 기간 말 누적 현금이 0 이상이 되기 위한 조건입니다. 실제로 그 출하량을 달성하거나 설비가 그 증가분을 만든다는 예측은 아닙니다. ${escape(result.period_note)}</p>`;
  $('cashflow-detail').innerHTML = `<table><thead><tr><th>연도</th><th>도입안 교체 지출</th><th>기존 유지안 교체 지출</th><th>기준 현금흐름</th><th>누적 현금</th></tr></thead><tbody>${base.cash_flows_krw.map((amount, year) => `<tr><td>${year === 0 ? '시작 시점' : `${year}년차 말`}</td><td>${year === 0 ? '—' : money(state.payload.replacements_krw[year] ?? 0)}</td><td>${year === 0 ? '—' : money(state.payload.baseline?.replacements_krw[year] ?? 0)}</td><td>${money(amount)}</td><td>${money(base.cumulative_cash_flows_krw[year])}</td></tr>`).join('')}</tbody></table>`;
  $('evidence-ledger').innerHTML = `<table><thead><tr><th>적용 항목</th><th>근거 종류</th><th>출처·산출근거</th><th>대상</th></tr></thead><tbody>${result.evidence_ledger.map(row => `<tr><td>${escape(row.label)}</td><td>${escape(SOURCE_LABELS[row.source_kind])}<br><small>사용자 입력 · 원문 미검증</small></td><td class="long">${escape(row.source_ref)}</td><td>${escape(row.scope.facility_id)}<br>${formatted(row.scope.area_m2)}㎡<br>${escape(row.scope.financial_start)}~${escape(row.scope.financial_end)}</td></tr>`).join('')}</tbody></table>`;
  $('download-result').disabled = false;
  $('result').focus({preventScroll: true});
  $('result').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function setRowValues(row, values) {
  for (const [name, value] of Object.entries(values)) row.querySelector(`[data-field="${name}"]`).value = value;
}

function resetRows() {
  for (const id of ['sales-rows', 'investment-rows', 'replacement-rows', 'baseline-sales-rows', 'baseline-replacement-rows']) $(id).replaceChildren();
  addSale('sales-rows'); addSale('baseline-sales-rows'); addInvestment();
  renderCosts('cost-rows'); renderCosts('baseline-cost-rows');
}

function clearForm() {
  $('facility-form').reset();
  resetRows();
  state.evidenceTarget = null; state.bound = false; state.result = null; state.payload = null; state.example = false;
  $('example-label').hidden = true; $('result').hidden = true; $('form-error').hidden = true;
  $('prediction-preview').hidden = true; $('rebind-area').hidden = true; $('budget-inputs').disabled = true;
  $('binding-status').textContent = '먼저 대상 시설을 입력하세요.';
  $('download-result').disabled = true;
  updateMode();
  if (state.model) updateDistrict();
}

function loadExample() {
  clearForm();
  state.example = true; $('example-label').hidden = false;
  const query = state.model.example_query;
  for (const [id, value] of Object.entries({'plan-id': '가상 시연 계획', 'facility-id': '가상 딸기 1동', 'area-m2': 1000, mode: 'new',
    variety: query.variety, region: query.region, 'facility-type': query.facility_type,
    'cycle-start': '2026-09-01', 'cycle-end': '2027-05-31', 'financial-start': '2026-09-01', 'financial-end': '2027-08-31', horizon: 10, discount: 4})) $(id).value = value;
  updateDistrict(); $('district').value = query.district;
  if (!bindTarget()) return;
  const source = {source_kind: 'budget', source_ref: '사용법 설명을 위한 가상 값. 실제 농가 기록·견적 아님.'};
  setRowValues($('sales-rows').firstElementChild, {...source, label: '가상 판매계획', share_percent: 100, net_price_krw_per_kg: 10000, sale_start: '2026-12-01', sale_end: '2027-05-31'});
  const amounts = {seedlings: 2000000, fertilizer_crop_protection: 1000000, energy_water: 3000000, hired_labor: 4000000,
    packaging_transport: 500, rent: 1000000, repairs_other: 500000, depreciation: 3000000, family_labor: 6000000};
  for (const row of $('cost-rows').children) setRowValues(row, {...source, amount_krw: amounts[row.dataset.category], basis: row.dataset.category === 'packaging_transport' ? 'per_kg' : 'annual_total'});
  setRowValues($('investment-rows').firstElementChild, {...source, label: '가상 시설 설치 총액', amount_krw: 100000000, coverage: '설비·온실·설치·부가세를 포함한다고 가정한 가상 총액. 실제 계약·견적 없음.'});
  for (const id of ['investment-confirmed', 'replacement-confirmed', 'period-ack', 'repeat-plan']) $(id).checked = true;
  $('yield-change').value = 20; $('price-change').value = 20; $('cost-change').value = 10;
  $('use-sensitivity').checked = true;
  $('binding-status').textContent += ' 현재 금액은 모두 가상 시연 값입니다. 계산 버튼으로 결과를 확인하세요.';
}

$('facility-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const invalid = [...$('facility-form').querySelectorAll('input,select')].find(control => !control.disabled && !control.checkValidity());
    if (invalid) {
      for (let parent = invalid.parentElement; parent && parent !== $('facility-form'); parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
      invalid.reportValidity();
      return;
    }
    const payload = buildPayload();
    const result = evaluateFacilityPlan(payload);
    state.payload = payload; state.result = result;
    $('form-error').hidden = true;
    renderResult(result);
  } catch (error) {showError(error.message);}
});
$('facility-form').addEventListener('input', event => {
  invalidateResult();
  if ($('target-inputs').contains(event.target)) invalidateBinding();
});
$('region').addEventListener('change', updateDistrict);
$('mode').addEventListener('change', updateMode);
$('bind-target').addEventListener('click', bindTarget);
$('load-example').addEventListener('click', loadExample);
$('clear-form').addEventListener('click', clearForm);
$('add-sale').addEventListener('click', () => {addSale('sales-rows'); invalidateResult();});
$('add-baseline-sale').addEventListener('click', () => {addSale('baseline-sales-rows'); invalidateResult();});
$('add-investment').addEventListener('click', () => {addInvestment(); invalidateResult();});
$('add-replacement').addEventListener('click', () => {addReplacement('replacement-rows'); invalidateResult();});
$('add-baseline-replacement').addEventListener('click', () => {addReplacement('baseline-replacement-rows'); invalidateResult();});
$('download-result').addEventListener('click', () => {
  if (!state.result || $('download-result').disabled) return;
  const record = {schema_version: 1, exported_at: new Date().toISOString(), is_synthetic_example: state.example,
    model_sha256: state.modelHash, inputs: state.payload, results: state.result,
    document_verification: '사용자가 입력한 근거이며 원문 진위는 독립 검증하지 않았습니다.'};
  const blob = new Blob([JSON.stringify(record, null, 2)], {type: 'application/json;charset=utf-8'});
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = 'facility-plan-result.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$('baseline-source-kind').innerHTML = sourceOptions;
resetRows();
try {
  const [response, validationResponse] = await Promise.all([fetch('./data/planning_models.json'), fetch('./data/planning_validation_summary.json')]);
  if (!response.ok || !validationResponse.ok) throw new Error('모델 파일을 읽을 수 없습니다.');
  const bytes = await response.arrayBuffer(), validation = await validationResponse.json();
  state.modelHash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (state.modelHash !== validation.models_sha256) throw new Error('학습 모델과 검증 보고서가 일치하지 않습니다.');
  state.model = JSON.parse(new TextDecoder().decode(bytes)).models.shipment;
  const support = state.model.support.by_crop?.['딸기'] ?? state.model.support;
  fillOptions('variety', support.categories.variety); fillOptions('region', support.categories.region);
  fillOptions('facility-type', support.categories.facility_type); fillOptions('district', []);
  const metrics = state.model.validation.metrics;
  $('validation-description').textContent = `${state.model.training_rows}작기 · ${state.model.training_facilities}시설. 시설을 분리한 중첩 검증 평균 절대오차: 모델 선택 절차 ${formatted(metrics.nested_selection.mae)}kg, 면적당 중앙값 ${formatted(metrics.baseline.mae)}kg. 현재 선택 절차가 단순 기준보다 더 정확하다고 확인되지 않았습니다. 이 오차는 개인 농가의 예측구간이나 소득 오차가 아닙니다.`;
  $('model-load-status').textContent = '학습 모델과 검증 파일의 해시를 확인했습니다. 아직 시설·판매·비용은 입력되지 않았습니다.';
  $('target-inputs').disabled = false; $('bind-target').disabled = false; $('load-example').disabled = false;
} catch (error) {
  $('model-load-status').textContent = `모델을 불러오지 못해 계산을 시작할 수 없습니다. ${error.message}`;
  $('model-load-status').className = 'error';
}
