// tests/dashboard/test_tokens.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const { checkAbsent } = require('./tokens_absent');

const page = load();
const { RAW, byId, charts } = page;
const T = RAW.summary.tokens;
if (!T || !T.per_day.length) {
  // CLOCWORK_DASH_WORKSPACE can point at a real workspace whose repository
  // was never worked on with Claude Code here; the page then owes it nothing
  // about tokens, and the checks further down have no subject.
  checkAbsent(page, check, section);
  done();
  return;
}
const en = new Intl.NumberFormat('en-US');
const enPct = new Intl.NumberFormat('en-US', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const card = label => byId('tokenStats').children.find(x => x.children[0].textContent === label);
const cardValue = label => { const c = card(label); return c && c.children[1].textContent; };
const cardNote = label => { const c = card(label); return c && c.children[2] && c.children[2].textContent; };

section('token section present');
check(byId('tokenSection').hidden === false, 'token section is shown when the workspace has token data');
check(page.headers.some(h => h.getAttribute('data-sort') === 'tokens'), 'Tokens column present');

section('token cards');
check(byId('tokenStats').children.length === 7, 'seven token cards');
check(/^~\d+B$/.test(cardValue('Tokens (lifetime est. ceiling)')), 'lifetime card is coarse, en-US compact: ' + cardValue('Tokens (lifetime est. ceiling)'));
check(cardValue('Measured').indexOf('B') > 0 || cardValue('Measured').indexOf('M') > 0, 'measured card is abbreviated');
check(cardValue('Cache Read') === enPct.format(T.cache_read_share), 'cache read share');
check(cardValue('Output per Line') === en.format(T.output_per_line), 'output per line');
check(byId('tokenNote').textContent.indexOf('30 days') > 0, 'note explains the retention window');

section('clarifications and footprint');
check(/re-read|context/i.test(cardNote('Cache Read') || ''), 'cache read card explains itself: ' + cardNote('Cache Read'));
check(/line/i.test(cardNote('Output per Line') || ''), 'output per line card explains itself: ' + cardNote('Output per Line'));
check(/kWh|MWh/.test(cardValue('Electricity (est.)') || ''), 'electricity card carries a unit: ' + cardValue('Electricity (est.)'));
// ECMA-402 exposes no measurement system, so the page derives it from the
// region: en-US maximises to the US, which is on US customary units.
const lb = new Intl.NumberFormat('en-US', { style: 'unit', unit: 'pound', maximumSignificantDigits: 2 });
check(cardValue('CO\u2082e (est.)') === lb.formatRange(T.co2_kg * 2.20462262, T.co2_kg * 2.20462262), 'co2 card in pounds for a US-customary region: ' + cardValue('CO\u2082e (est.)'));
check((cardNote('Electricity (est.)') || '').length > 0 && (cardNote('CO\u2082e (est.)') || '').length > 0,
      'both footprint cards state their assumption');
// The footprint follows the token ceiling, so it must not be presented as measured.
check(/order[- ]of[- ]magnitude|rough/i.test(byId('tokenNote').textContent), 'note flags the footprint as order-of-magnitude');

section('api cost');
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumSignificantDigits: 2 });
const usdExact = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
check(typeof T.lifetime_cost_usd === 'number' && T.lifetime_cost_usd > 0, 'blob carries a lifetime cost');
check(cardValue('API Cost (est.)') === usd.formatRange(T.lifetime_cost_usd, T.lifetime_cost_usd), 'cost card: coarse dollars at list prices: ' + cardValue('API Cost (est.)'));
check((cardNote('API Cost (est.)') || '').indexOf(usdExact.format(T.cost_usd)) === 0 && /measured/.test(cardNote('API Cost (est.)') || ''), 'cost note leads with the measured window figure: ' + cardNote('API Cost (est.)'));
check(/list price/i.test(byId('tokenNote').textContent), 'note explains the cost basis');

section('token chart');
const token = charts[charts.length - 1];
check(charts.length === 6, 'token chart is the sixth chart');
const estimated = token.data.datasets[0];
const measured = token.data.datasets[1];
check(estimated.label === 'Estimated' && measured.label === 'Measured', 'two labelled datasets');
check(estimated.data.length === T.per_day.filter(r => r[2] === 'e').length, 'estimated points match the e rows');
check(measured.data.length === T.per_day.filter(r => r[2] === 'm').length, 'measured points match the m rows');
check(measured.data.every(p => typeof p.x === 'string' && typeof p.y === 'number'), 'measured points are {x,y}');

section('independent of the selection');
const before = [cardValue('Tokens (lifetime est.)'), cardValue('Measured'), cardValue('Output per Line')];
const updatesBefore = token.updates;
page.run('SEL.set({ lang: "' + RAW.languages[0] + '", type: "comment" })');
const after = [cardValue('Tokens (lifetime est.)'), cardValue('Measured'), cardValue('Output per Line')];
check(before.join('|') === after.join('|'), 'token cards ignore the Language and Line type selection');
check(token.updates === updatesBefore, 'token chart does not re-render on selection change');

done();
