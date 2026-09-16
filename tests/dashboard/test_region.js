// tests/dashboard/test_region.js
// The blob carries the region locale of the machine that generated the page
// (macOS keeps language and region apart, and browsers expose only the
// language list). When present it must win over navigator; when absent or
// unusable, navigator is the fallback.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const REGION = 'en-SE';
const page = load({ locale: 'en-US', region: REGION });
const { RAW, byId, cells } = page;
const S = RAW.summary;
const int = new Intl.NumberFormat(REGION);
const pct = new Intl.NumberFormat(REGION, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const date = iso => { const p = iso.split('-').map(Number); return new Intl.DateTimeFormat(REGION, { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(p[0], p[1] - 1, p[2])); };
const value = label => byId('statsGrid').children.find(x => x.children[0].textContent === label).children[1].textContent;

section('embedded region locale wins over the browser language');
check(int.format(3744) !== new Intl.NumberFormat('en-US').format(3744), 'sanity: en-SE groups digits differently from en-US');
check(page.run('return FMT.locale') === REGION && page.run('return Chart.defaults.locale') === REGION, 'page and Chart.js use the embedded locale');
check(value('Total Commits') === int.format(S.total_commits), 'commit count in the region format: ' + value('Total Commits'));
check(value('AI-Assisted') === int.format(S.ai_assisted_commits) + ' (' + pct.format(S.ai_assisted_commits / S.total_commits) + ')', 'percentage in the region format: ' + value('AI-Assisted'));
const top = byId('allCommitsBody').children[0];
check(cells(top)[0] === date(RAW.commits[RAW.commits.length - 1][2]), 'table date in the region format: ' + cells(top)[0]);
const T = S.tokens;
const hasTokens = !!(T && T.per_day.length);   // the page shows no token element without data
const co2 = p => p.byId('tokenStats').children.find(x => x.children[0].textContent === 'CO\u2082e (est.)').children[1].textContent;
const massFmt = (tag, unit) => new Intl.NumberFormat(tag, { style: 'unit', unit, maximumSignificantDigits: 2 });
const inKg = tag => massFmt(tag, 'kilogram').formatRange(T.co2_kg, T.co2_kg);
const inLb = tag => massFmt(tag, 'pound').formatRange(T.co2_kg * 2.20462262, T.co2_kg * 2.20462262);
if (hasTokens) check(T.co2_kg < 1000, 'sanity: the CO\u2082e figure is below a tonne, so the kilogram branch is what renders');
if (hasTokens) check(co2(page) === inKg(REGION), 'a metric region shows kilograms: ' + co2(page));

section('measurement system can be pinned in the tag');
const usMetric = load({ locale: 'en-US', region: 'en-US-u-ms-metric' });
if (hasTokens) check(co2(usMetric) === inKg('en-US'), 'en-US with -u-ms-metric shows kilograms: ' + co2(usMetric));
const seCustomary = load({ locale: 'en-US', region: 'en-SE-u-ms-ussystem' });
if (hasTokens) check(co2(seCustomary) === inLb('en-SE'), 'en-SE with -u-ms-ussystem shows pounds: ' + co2(seCustomary));
check(seCustomary.run('return FMT.locale') === 'en-SE', 'the extension does not leak into the resolved locale');

section('unusable embedded tag falls back to the browser');
const bad = load({ locale: 'de-DE', region: 'not a locale!' });
check(bad.run('return FMT.locale') === 'de-DE', 'invalid tag ignored, navigator used: ' + bad.run('return FMT.locale'));
check(bad.byId('statsGrid').children.find(x => x.children[0].textContent === 'Total Commits').children[1].textContent === new Intl.NumberFormat('de-DE').format(S.total_commits), 'and the numbers follow it');

done();
