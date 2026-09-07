// tests/dashboard/test_tokens.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId, charts } = page;
const T = RAW.summary.tokens;
const cardValue = label => {
  const c = byId('tokenStats').children.find(x => x.children[0].textContent === label);
  return c && c.children[1].textContent;
};

section('token cards');
check(byId('tokenStats').children.length === 4, 'four token cards');
check(/^~\d+ B$/.test(cardValue('Tokens (lifetime est.)')), 'lifetime card is coarse: ' + cardValue('Tokens (lifetime est.)'));
check(cardValue('Measured').indexOf('B') > 0 || cardValue('Measured').indexOf('M') > 0, 'measured card is abbreviated');
check(cardValue('Cache Read') === (T.cache_read_share * 100).toFixed(1) + '%', 'cache read share');
check(cardValue('Output per Line') === T.output_per_line.toLocaleString(), 'output per line');
check(byId('tokenNote').textContent.indexOf('30 days') > 0, 'note explains the retention window');

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
