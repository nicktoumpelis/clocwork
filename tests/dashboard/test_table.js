// tests/dashboard/test_table.js
'use strict';
const fs = require('fs');
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId, headers, tabs, cells } = page;
const tbody = byId('allCommitsBody'), count = byId('allCommitsCount'), search = byId('commitSearch'), bar = byId('filterBar');
const [, thDate, , thMsg, thAgent, thChurn, thNet, thCumul] = headers;
const chip = name => bar.children.find(b => b.textContent === name);
const num = s => parseInt(String(s).replace(/[+,]/g, ''), 10);
const rows = () => tbody.children.filter(r => r.className.indexOf('detail-row') < 0);
const total = RAW.commits.length;
const en = n => new Intl.NumberFormat('en-US').format(n);
// Date cells are locale-formatted, so order is checked via the commit's ISO date.
const isoOf = r => RAW.commits.find(c => c[1] === cells(r)[1])[2];

// Read agent counts from summary cards (independent rendered source)
const findSummaryCard = (label) => {
  const statsGrid = byId('statsGrid');
  for (const card of statsGrid.children) {
    const labelChild = Array.from(card.children).find(c => c.className === 'label');
    const valueChild = Array.from(card.children).find(c => c.className === 'value');
    if (labelChild && labelChild.textContent === label && valueChild) {
      return parseInt(valueChild.textContent.replace(/,/g, ''), 10);
    }
  }
  return 0;
};
const miscCount = findSummaryCard('Misc (merges)');
const humanCount = findSummaryCard('Human Only');

section('default render');
check(rows().length === 500, 'caps at 500 rows');
check(count.textContent === en(total) + ' commits · showing first 500', 'headline for full list');
check(cells(rows()[0])[1].length === 7, 'SHA in its own column');
check(thDate.getAttribute('data-dir') === 'desc', 'date sorted desc by default');
check(isoOf(rows()[0]) >= isoOf(rows()[499]), 'newest first');

section('filter chips');
chip('Misc').fire('click');
check(new RegExp('^' + en(miscCount) + ' of ' + en(total) + ' commits · Misc').test(count.textContent), 'Misc headline');
check(rows().every(r => cells(r)[3] === 'Misc'), 'only Misc rows');
chip('Human').fire('click');
check(new RegExp('^' + en(humanCount) + ' of ' + en(total) + ' commits · Human').test(count.textContent), 'Human headline');
check(rows().every(r => cells(r)[3] === 'Human'), 'only Human rows');

section('sorting');
thDate.fire('click');
check(thDate.getAttribute('data-dir') === 'asc' && isoOf(rows()[0]) <= isoOf(rows()[rows().length - 1]), 'date asc');
thMsg.fire('click');
let msgs = rows().map(r => cells(r)[2].toLowerCase());
check(thMsg.getAttribute('data-dir') === 'asc' && thDate.getAttribute('data-dir') === null && msgs.every((m, i) => i === 0 || msgs[i - 1] <= m), 'message asc, date indicator cleared');
thAgent.fire('click');
let ag = rows().map(r => cells(r)[3].toLowerCase());
check(ag.every((a, i) => i === 0 || ag[i - 1] <= a), 'agent asc');
thChurn.fire('click');
let ch = rows().map(r => { const [a, d] = cells(r)[4].split(' / '); return Math.abs(num(a)) + Math.abs(num(d)); });
check(thChurn.getAttribute('data-dir') === 'desc' && ch.every((v, i) => i === 0 || ch[i - 1] >= v), 'churn desc');
thNet.fire('click');
let nets = rows().map(r => num(cells(r)[5]));
check(thNet.getAttribute('data-dir') === 'desc' && nets.every((v, i) => i === 0 || nets[i - 1] >= v), 'net desc');
thCumul.fire('click'); thCumul.fire('click');
let cu = rows().map(r => num(cells(r)[6]));
check(thCumul.getAttribute('data-dir') === 'asc' && cu.every((v, i) => i === 0 || cu[i - 1] <= v), 'cumulative asc after two clicks');

section('search');
chip('All').fire('click'); thDate.fire('click');
search.value = 'font'; search.fire('input');
check(rows().length > 0 && rows().every(r => cells(r)[2].toLowerCase().includes('font')), 'search matches message');
const someSha = cells(rows()[0])[1];
search.value = someSha; search.fire('input');
check(rows().length === 1 && count.textContent === '1 of ' + en(total) + ' commits', 'search by SHA gives one row');
search.value = ''; search.fire('input');

section('tabs');
tabs[1].fire('click');
check(rows().length === 25 && count.textContent === '25 commits', 'gains tab has 25 rows');
check(thNet.getAttribute('data-dir') === 'desc', 'gains default net desc');
check(rows().every(r => cells(r)[3] !== 'Misc'), 'no merges in gains');
tabs[2].fire('click');
check(rows().length === 15 && thNet.getAttribute('data-dir') === 'asc', 'drops tab has 15 rows net asc');
tabs[0].fire('click');
check(thDate.getAttribute('data-dir') === 'desc' && rows().length === 500, 'all tab resets to date desc');

section('links, widths, expansion');
const first = rows()[0];
const shaEl = first.children[2].children[0], msgEl = first.children[3].children[0];
check(shaEl.tagName === 'a' && shaEl.href === RAW.summary.repo_url + '/commit/' + shaEl.textContent && shaEl.target === '_blank', 'SHA links to GitHub');
check(msgEl.tagName === 'a' && msgEl.href === shaEl.href, 'message links to the same commit');
const widths = page.cols.map(c => parseFloat(c.style.width));
check(widths.every(w => w >= 32) && byId('allCommitsTable').style.tableLayout === 'fixed', 'column widths applied with fixed layout');
check(headers.every(h => h.children.some(x => x.className === 'col-resizer')), 'every header has a resize handle');
const handle = thDate.children.find(x => x.className === 'col-resizer');
const docListeners = {}; document.addEventListener = (t, f) => { docListeners[t] = f; }; document.removeEventListener = () => {};
handle.fire('pointerdown', { preventDefault() {}, stopPropagation() {}, clientX: 100 });
docListeners.pointermove({ clientX: 150 }); docListeners.pointerup();
check(parseFloat(page.cols[1].style.width) === widths[1] + 50, 'drag widens Date by 50px');
first.fire('click');
check(first.className.includes('expanded') && first.nextSibling.className === 'detail-row', 'row expands');
const script = page.head.children.find(e => e.tagName === 'script');
check(script && script.src === 'commit_bodies.js', 'sidecar injected on first expand');
new Function(fs.readFileSync(page.bodiesFile, 'utf8') + '; window.COMMIT_BODIES = COMMIT_BODIES;')();
script.onload();
const detail = first.nextSibling.children[0].children[0];
const expectedBody = COMMIT_BODIES[cells(first)[1]] || '';
check(detail.children[0].textContent === cells(first)[2], 'detail title is the subject');
check(expectedBody ? detail.children[1].textContent === expectedBody : detail.children[1].textContent === 'No further description.', 'detail body from sidecar');
first.fire('click');
check(!first.className.includes('expanded'), 'second click collapses');

section('selection drives the table');
page.run('SEL.set({ lang: "' + RAW.languages[0] + '", type: "total" })');
const stSel = page.run('return SEL.stats()');
tabs[0].fire('click'); search.value = ''; search.fire('input'); chip('All').fire('click');
const newest = rows()[0];
const newestIdx = RAW.commits.length - 1;
check(cells(newest)[1] === RAW.commits[newestIdx][1], 'newest row is the last commit');
check(num(cells(newest)[5]) === stSel.net[newestIdx] && num(cells(newest)[6]) === stSel.cumulative[newestIdx], 'net and cumulative follow the selection');
check(cells(newest)[4] === '+' + en(stSel.added[newestIdx]) + ' / -' + en(stSel.removed[newestIdx]), '+/- follows the selection');
tabs[1].fire('click');
check(rows().map(r => cells(r)[1]).join() === stSel.gains.map(i => RAW.commits[i][1]).join(), 'gains tab lists SEL.stats().gains in order');
check(tabs[1].textContent === 'Biggest ' + RAW.languages[0] + ' LOC Gains' && tabs[2].textContent === 'Biggest ' + RAW.languages[0] + ' LOC Drops', 'tab labels follow the selection');
tabs[0].fire('click');

section('per-language columns');
{
  const LANGS = RAW.languages;
  const langNet = (row, li, type) => {
    let a = 0, r = 0;
    row[6].forEach(([idx, v]) => { if (idx !== li) return; if (type === 'total') { a += v[0] + v[2] + v[4]; r += v[1] + v[3] + v[5]; } else { const t = { code: 0, comment: 1, blank: 2 }[type]; a += v[2 * t]; r += v[2 * t + 1]; } });
    return a - r;
  };
  page.run('SEL.set({ lang: "All", type: "code", tests: false })');
  tabs[0].fire('click'); search.value = ''; search.fire('input'); chip('All').fire('click'); thDate.fire('click');
  if (thDate.getAttribute('data-dir') !== 'desc') thDate.fire('click');
  check(headers.length === 8 + LANGS.length && page.cols.length === headers.length, 'one header and col per language after the fixed columns');
  check(headers.slice(8).map(h => h.textContent).join('|') === LANGS.join('|'), 'language headers in data order');
  check(headers.slice(8).every((h, i) => h.className.indexOf('sortable') >= 0 && h.getAttribute('data-sort') === 'lang:' + i), 'language headers sortable with lang:<idx> keys');
  const top = rows()[0];
  const topRaw = RAW.commits.find(c => c[1] === cells(top)[1]);
  let ok = true;
  LANGS.forEach((l, li) => {
    const expected = langNet(topRaw, li, 'code');
    const cell = cells(top)[7 + li];
    const shown = cell === '' ? 0 : num(cell);
    if (shown !== expected || (expected === 0 && cell !== '')) ok = false;
  });
  check(ok, 'newest row language cells equal an independent per-language net (blank for zero)');
  // find a row with a non-zero Swift net and check the badge sign class
  const swiftIdx = LANGS.indexOf('Swift');
  const rowWithSwift = rows().find(r => cells(r)[7 + swiftIdx] !== '');
  check(!!rowWithSwift && rowWithSwift.children[8 + swiftIdx].children[0].className.indexOf(num(cells(rowWithSwift)[7 + swiftIdx]) >= 0 ? 'positive' : 'negative') >= 0, 'non-zero language cell is a signed badge');
  headers[8 + swiftIdx].fire('click');
  let vals = rows().map(r => { const c = cells(r)[7 + swiftIdx]; return c === '' ? 0 : num(c); });
  check(headers[8 + swiftIdx].getAttribute('data-dir') === 'desc' && vals.every((v, i) => i === 0 || vals[i - 1] >= v), 'clicking a language header sorts by that language, largest first');
  headers[8 + swiftIdx].fire('click');
  vals = rows().map(r => { const c = cells(r)[7 + swiftIdx]; return c === '' ? 0 : num(c); });
  check(vals.every((v, i) => i === 0 || vals[i - 1] <= v), 'second click reverses');
  page.run('SEL.set({ type: "comment" })');
  thDate.fire('click'); if (thDate.getAttribute('data-dir') !== 'desc') thDate.fire('click');
  const top2 = rows()[0]; const top2Raw = RAW.commits.find(c => c[1] === cells(top2)[1]);
  ok = LANGS.every((l, li) => { const cell = cells(top2)[7 + li]; return (cell === '' ? 0 : num(cell)) === langNet(top2Raw, li, 'comment'); });
  check(ok, 'language cells follow the Line type selection');
  page.run('SEL.set({ lang: "' + LANGS[0] + '" })');
  const top3 = rows()[0]; const top3Raw = RAW.commits.find(c => c[1] === cells(top3)[1]);
  ok = LANGS.every((l, li) => { const cell = cells(top3)[7 + li]; return (cell === '' ? 0 : num(cell)) === langNet(top3Raw, li, 'comment'); });
  check(ok, 'language cells ignore the Language selection');
  top3.fire('click');
  check(top3.nextSibling.className === 'detail-row' && top3.nextSibling.children[0].colSpan === headers.length, 'detail row spans every column');
  top3.fire('click');
  page.run('SEL.set({ lang: "All", type: "code" })');
}

done();
