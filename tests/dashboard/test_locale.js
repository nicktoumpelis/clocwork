// tests/dashboard/test_locale.js
// Loads the page as a German viewer and checks that every rendered number,
// percentage, compact figure and date follows that locale instead of the
// en-US conventions the page used to hardcode. Expected strings come from
// Intl itself so the test does not bake in one ICU version's spelling.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const LOCALE = 'de-DE';
const page = load({ locale: LOCALE });
const { RAW, byId, charts, cells } = page;
const S = RAW.summary, T = S.tokens;
const hasTokens = !!(T && T.per_day && T.per_day.length);   // the page shows no token element without data
const st = page.run('return SEL.stats()');

const int = new Intl.NumberFormat(LOCALE);
const signed = new Intl.NumberFormat(LOCALE, { signDisplay: 'always' });
const pct = new Intl.NumberFormat(LOCALE, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumSignificantDigits: 3 });
const compactWhole = new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 0 });
const sig2 = new Intl.NumberFormat(LOCALE, { maximumSignificantDigits: 2 });
const kg = new Intl.NumberFormat(LOCALE, { style: 'unit', unit: 'kilogram', maximumSignificantDigits: 2 });
// Intl's own approximation sign for this locale (≈ in German) and the gap it
// puts between a number and a unit symbol; both must carry over to the
// units Intl cannot format itself.
const approx = f => n => f.formatRange(n, n);
const approxSign = sig2.formatRange(9, 9).replace(/\d/g, '');
const unitSep = kg.formatToParts(9).find(p => p.type === 'literal').value;
// The region's date format is the numeric one: 07.09.2026 in Germany, 2026-09-07 in Sweden.
const numeric = new Intl.DateTimeFormat(LOCALE, { year: 'numeric', month: '2-digit', day: '2-digit' });
const monthLong = new Intl.DateTimeFormat(LOCALE, { month: 'long', year: 'numeric' });
const monthShort = new Intl.DateTimeFormat(LOCALE, { month: 'short', year: 'numeric' });
const local = iso => { const p = iso.split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); };
const date = iso => numeric.format(local(iso));

const card = (grid, label) => byId(grid).children.find(x => x.children[0].textContent === label);
const value = (grid, label) => { const c = card(grid, label); return c && c.children[1].textContent; };
const note = (grid, label) => { const c = card(grid, label); return c && c.children[2] && c.children[2].textContent; };

section('viewer locale');
check(int.format(1234) === '1.234' && pct.format(0.123) !== '12.3%', 'sanity: node ICU formats de-DE differently from en-US');
check(page.run('return Chart.defaults.locale') === LOCALE, 'Chart.js is told the viewer locale');

section('summary cards');
check(value('statsGrid', 'Total Commits') === int.format(S.total_commits), 'commit count grouped the German way: ' + value('statsGrid', 'Total Commits'));
// The count alone is the value, so it never wraps; the share is the line beneath.
check(value('statsGrid', 'AI-Assisted') === int.format(S.ai_assisted_commits), 'AI-assisted count alone: ' + value('statsGrid', 'AI-Assisted'));
check(note('statsGrid', 'AI-Assisted') === pct.format(S.ai_assisted_commits / S.total_commits) + ' of all commits',
      'AI-assisted share as a German percentage on its own line: ' + note('statsGrid', 'AI-Assisted'));
check(!note('statsGrid', 'Total Commits'), 'a tile without a note has no second line');
check(value('statsGrid', 'Peak') === int.format(st.peak.value), 'peak lines');
check(value('statsGrid', 'Peak Date') === date(st.peak.date), 'peak date in the numeric region format: ' + value('statsGrid', 'Peak Date'));
check(value('statsGrid', 'First Commit') === date(S.first_date) && value('statsGrid', 'Last Commit') === date(S.last_date), 'first and last commit dates');

section('header and footer');
check(byId('headerCommits').textContent === int.format(S.total_commits), 'header commit count');
check(byId('headerFrom').textContent === monthLong.format(local(S.first_date)) && byId('headerTo').textContent === monthLong.format(local(S.last_date)),
      'header month range: ' + byId('headerFrom').textContent + ' to ' + byId('headerTo').textContent);
check(byId('footerCommits').textContent === int.format(S.total_commits), 'footer commit count');
check(typeof RAW.generated === 'string' && byId('generatedOn').textContent === date(RAW.generated), 'generation date from the data blob: ' + byId('generatedOn').textContent);

if (hasTokens) {
section('token cards');
check(value('tokenStats', 'Tokens (lifetime est. ceiling)') === approx(compactWhole)(T.lifetime_total), 'lifetime ceiling: German approximation sign and compact billion: ' + value('tokenStats', 'Tokens (lifetime est. ceiling)'));
check(value('tokenStats', 'Measured') === compact.format(T.measured_total), 'measured total compact: ' + value('tokenStats', 'Measured'));
check(value('tokenStats', 'Cache Read') === pct.format(T.cache_read_share), 'cache read share: ' + value('tokenStats', 'Cache Read'));
check(value('tokenStats', 'Output per Line') === int.format(T.output_per_line), 'output per line');
check(note('tokenStats', 'Measured') === int.format(T.measured_days) + ' days from ' + date(T.coverage_start), 'coverage note date: ' + note('tokenStats', 'Measured'));
check(value('tokenStats', 'Electricity (est.)') === (T.energy_kwh >= 1000 ? approx(sig2)(T.energy_kwh / 1000) + unitSep + 'MWh' : approx(sig2)(T.energy_kwh) + unitSep + 'kWh'),
      'electricity: German approximation sign, decimal and unit gap: ' + value('tokenStats', 'Electricity (est.)'));
check(value('tokenStats', 'CO₂e (est.)') === (T.co2_kg >= 1000 ? approx(sig2)(T.co2_kg / 1000) + unitSep + 't' : approx(kg)(T.co2_kg)),
      'co2e: Intl kilogram formatting with the German approximation sign: ' + value('tokenStats', 'CO₂e (est.)'));
check(approxSign !== '~', 'sanity: the German approximation sign is not the ASCII tilde');
check(note('tokenStats', 'CO₂e (est.)') === 'at ' + int.format(400) + ' g/kWh, location-based', 'grid intensity note');
const usd = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'USD', maximumSignificantDigits: 2 });
check(value('tokenStats', 'API Cost (est.)') === usd.formatRange(T.lifetime_cost_usd, T.lifetime_cost_usd), 'api cost in the German currency format: ' + value('tokenStats', 'API Cost (est.)'));
check(byId('tokenNote').textContent.indexOf(int.format(T.measured_total)) > 0 && byId('tokenNote').textContent.indexOf(int.format(Math.round(T.ratio))) > 0,
      'token note numbers grouped the German way');

}

section('commit table');
const rows = () => byId('allCommitsBody').children.filter(r => r.className.indexOf('detail-row') < 0);
const top = rows()[0], i = RAW.commits.length - 1;
check(cells(top)[1] === RAW.commits[i][1], 'sanity: newest commit first');
check(cells(top)[0] === date(RAW.commits[i][2]), 'date column: ' + cells(top)[0]);
check(cells(top)[4] === signed.format(st.added[i]) + ' / ' + signed.format(-st.removed[i]), '+/- column: ' + cells(top)[4]);
check(cells(top)[5] === (st.net[i] === 0 ? '0' : signed.format(st.net[i])), 'net column: ' + cells(top)[5]);
check(cells(top)[6] === int.format(st.cumulative[i]), 'cumulative column: ' + cells(top)[6]);
check(byId('allCommitsCount').textContent === int.format(RAW.commits.length) + ' commits · showing first ' + int.format(500), 'headline: ' + byId('allCommitsCount').textContent);

section('agent cards');
const first = byId('agentGrid').children[0];
const name = first.children[0].textContent, a = st.agents[name];
const strong = first.children[1].children.map(d => d.children[0].textContent);
const unit = page.run('return SEL.shortLabel()');
check(strong[0] === int.format(a.commits), 'agent commits');
check(strong[1] === signed.format(a.added) + ' ' + unit && strong[2] === signed.format(-a.removed) + ' ' + unit && strong[3] === signed.format(a.net) + ' ' + unit,
      'agent added/deleted/net signed the German way: ' + strong.slice(1, 4).join(' | '));
check(strong[4] === date(a.first_date) + ' to ' + date(a.last_date), 'agent active range: ' + strong[4]);

section('charts');
const [main, daily, agentCum, pie, agentNet, token] = charts;
const sept = new Date(2026, 8, 1).getTime();
[['main', main], ['daily', daily], ['agent cumulative', agentCum]].concat(hasTokens ? [['token', token]] : []).forEach(([label, c]) => {
  const cb = c.options.scales.x.ticks && c.options.scales.x.ticks.callback;
  const out = typeof cb === 'function' ? cb(sept, 0, [{ value: sept }]) : undefined;
  check(out === monthShort.format(new Date(sept)), label + ' x-axis months in German: ' + out);
});
if (hasTokens) check(token.options.scales.y.ticks.callback(1500000) === compact.format(1500000), 'token y-axis compact: ' + token.options.scales.y.ticks.callback(1500000));
const tt = c => c.options.plugins.tooltip.callbacks;
check(tt(main).title([{ dataIndex: i }]) === date(RAW.commits[i][2]) + '  (' + RAW.commits[i][1] + ')', 'main tooltip title date: ' + tt(main).title([{ dataIndex: i }]));
const mainLabel = tt(main).label({ dataIndex: i, datasetIndex: 0, dataset: { label: 'Code Lines' }, parsed: { y: st.cumulative[i] } });
check(mainLabel[0] === '  Code Lines: ' + int.format(st.cumulative[i]) && mainLabel[1] === '  Delta: ' + signed.format(st.net[i]), 'main tooltip numbers: ' + mainLabel.slice(0, 2).join(' | '));
const d0 = st.daily[st.daily.length - 1];
check(tt(daily).title && tt(daily).title([{ raw: { x: d0.date } }]) === date(d0.date), 'daily tooltip title is a locale date');
const dl = tt(daily).label({ dataIndex: st.daily.length - 1, parsed: { y: d0.net } });
check(dl[0] === '  Delta: ' + signed.format(d0.net) && dl[1] === '  Commits: ' + int.format(d0.commits), 'daily tooltip numbers: ' + dl.slice(0, 2).join(' | '));
check(tt(agentCum).title && tt(agentCum).title([{ raw: { x: d0.date } }]) === date(d0.date)
      && tt(agentCum).label({ dataset: { label: 'Human' }, parsed: { y: -1234 } }) === '  Human: ' + signed.format(-1234), 'agent cumulative tooltip');
check(tt(pie).label({ label: 'Human', parsed: S.human_only_commits }) === '  Human: ' + int.format(S.human_only_commits) + ' commits (' + pct.format(S.human_only_commits / S.total_commits) + ')',
      'pie tooltip: ' + tt(pie).label({ label: 'Human', parsed: S.human_only_commits }));
const an = agentNet.data.labels[0], as = st.agents[an];
check(tt(agentNet).label({ dataIndex: 0, datasetIndex: 1 }) === '  Deleted: ' + signed.format(-as.removed) && tt(agentNet).afterBody([{ dataIndex: 0 }]) === '  Net: ' + signed.format(as.net), 'agent net tooltip');
if (hasTokens) check(tt(token).title && tt(token).title([{ raw: { x: d0.date } }]) === date(d0.date)
      && tt(token).label({ dataset: { label: 'Measured' }, parsed: { y: 1234567 } }) === '  Measured: ' + int.format(1234567), 'token tooltip');
const drift = page.run('return SEL.drift()');
if (drift !== 0) check(byId('reconNote').textContent.indexOf(signed.format(drift) + ' lines') > 0, 'reconciliation drift signed the German way');

done();
