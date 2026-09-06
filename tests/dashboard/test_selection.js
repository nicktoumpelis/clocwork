// tests/dashboard/test_selection.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

function pairFor(row, lang, type, LANGS, testsOnly) {
  const entries = testsOnly ? row[7] : row[6];
  let a = 0, r = 0;
  entries.forEach(([li, v]) => {
    if (lang !== 'All' && LANGS[li] !== lang) return;
    if (type === 'total') { a += v[0] + v[2] + v[4]; r += v[1] + v[3] + v[5]; }
    else { const t = { code: 0, comment: 1, blank: 2 }[type]; a += v[2 * t]; r += v[2 * t + 1]; }
  });
  return [a, r];
}

section('defaults and hash');
let page = load();
let { RAW } = page;
const LANGS = RAW.languages;
check(JSON.stringify(page.run('return SEL.get()')) === JSON.stringify({ lang: 'All', type: 'code', tests: false }), 'default selection');
page = load({ hash: '#lang=' + encodeURIComponent(LANGS[0]) + '&type=comment&tests=1' });
check(page.run('return SEL.get().lang') === LANGS[0] && page.run('return SEL.get().type') === 'comment' && page.run('return SEL.get().tests') === true, 'selection restored from hash');
page = load({ hash: '#lang=Nope&type=bogus' });
check(page.run('return SEL.get().lang') === 'All' && page.run('return SEL.get().type') === 'code', 'invalid hash values ignored');

section('aggregation');
page = load(); RAW = page.RAW;
let st = page.run('return SEL.stats()');
const n = RAW.commits.length;
let ok = true, cum = 0;
for (let i = 0; i < n; i++) {
  const [a, r] = pairFor(RAW.commits[i], 'All', 'code', LANGS, false);
  cum += a - r;
  if (st.added[i] !== a || st.removed[i] !== r || st.net[i] !== a - r || st.cumulative[i] !== cum) { ok = false; break; }
}
check(ok, 'added/removed/net/cumulative match a hand computation for All/code');
check(Object.keys(st.agents).reduce((s, a) => s + st.agents[a].commits, 0) === n, 'agent commit counts sum to total');
check(st.daily.length > 0 && st.daily[st.daily.length - 1].cumulative === st.cumulative[n - 1], 'daily series ends at the final cumulative');
check(st.gains.length === 25 && st.gains.every((idx, i) => i === 0 || st.net[st.gains[i - 1]] >= st.net[idx]) && st.gains.every(idx => !RAW.commits[idx][5]), 'gains: 25 non-merge, net desc');
check(st.drops.length === 15 && st.drops.every((idx, i) => i === 0 || st.net[st.drops[i - 1]] <= st.net[idx]), 'drops: 15, net asc');
check(st.peak.value === Math.max.apply(null, st.cumulative) && st.cumulative[st.peak.index] === st.peak.value, 'peak is the max cumulative');
const headAll = Object.keys(RAW.summary.head_snapshot.all).reduce((s, l) => s + RAW.summary.head_snapshot.all[l].code, 0);
check(page.run('return SEL.headTotal(false)') === headAll, 'headTotal sums the snapshot for the selection');

section('changing the selection');
let fired = 0;
page.run('SEL.on(function() { window.__fired = (window.__fired || 0) + 1; })');
page.run('SEL.set({ lang: "' + LANGS[0] + '", type: "total" })');
check(page.run('return window.__fired') === 1, 'listeners fire once per set');
check(page.location.hash === '#lang=' + encodeURIComponent(LANGS[0]) + '&type=total', 'hash written');
st = page.run('return SEL.stats()');
ok = true; cum = 0;
for (let i = 0; i < n; i++) {
  const [a, r] = pairFor(RAW.commits[i], LANGS[0], 'total', LANGS, false);
  cum += a - r;
  if (st.net[i] !== a - r || st.cumulative[i] !== cum) { ok = false; break; }
}
check(ok, 'stats recomputed for ' + LANGS[0] + '/total');
let tcum = 0; ok = true;
for (let i = 0; i < n; i++) { const [a, r] = pairFor(RAW.commits[i], LANGS[0], 'total', LANGS, true); tcum += a - r; if (st.testCumulative[i] !== tcum) { ok = false; break; } }
check(ok, 'test cumulative matches a hand computation');
check(page.run('return SEL.shortLabel()') === LANGS[0] + ' LOC', 'short label for lang/total');
page.run('SEL.set({ type: "comment" })');
check(page.run('return SEL.shortLabel()') === LANGS[0] + ' Comment LOC', 'short label for lang/comment');
page.run('SEL.set({ tests: true })');
check(page.run('return window.__fired') === 3 && page.location.hash.indexOf('&tests=1') > 0, 'tests toggle fires and is persisted');
page.run('SEL.set({ tests: true })');
check(page.run('return window.__fired') === 3, 'no-op set does not fire');

section('selector bar');
page = load(); RAW = page.RAW;
const langBar = page.byId('langSelector'), typeBar = page.byId('typeSelector');
check(langBar.children.map(b => b.textContent).join('|') === ['All'].concat(RAW.languages).join('|'), 'language buttons: All then every language');
check(typeBar.children.map(b => b.textContent).join('|') === 'Code|Comment|Blank|Total', 'line type buttons');
check(langBar.children[0].className === 'active' && typeBar.children[0].className === 'active', 'defaults highlighted');
langBar.children[1].fire('click'); typeBar.children[3].fire('click');
check(page.run('return SEL.get().lang') === RAW.languages[0] && page.run('return SEL.get().type') === 'total', 'clicking buttons sets the selection');
check(langBar.children[1].className === 'active' && langBar.children[0].className === '' && typeBar.children[3].className === 'active', 'active class follows the selection');

done();
