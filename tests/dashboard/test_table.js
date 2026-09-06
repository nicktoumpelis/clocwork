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
check(count.textContent === total.toLocaleString() + ' commits · showing first 500', 'headline for full list');
check(cells(rows()[0])[1].length === 7, 'SHA in its own column');
check(thDate.getAttribute('data-dir') === 'desc', 'date sorted desc by default');
check(cells(rows()[0])[0] >= cells(rows()[499])[0], 'newest first');

section('filter chips');
chip('Misc').fire('click');
check(new RegExp('^' + miscCount.toLocaleString() + ' of ' + total.toLocaleString() + ' commits · Misc').test(count.textContent), 'Misc headline');
check(rows().every(r => cells(r)[3] === 'Misc'), 'only Misc rows');
chip('Human').fire('click');
check(new RegExp('^' + humanCount.toLocaleString() + ' of ' + total.toLocaleString() + ' commits · Human').test(count.textContent), 'Human headline');
check(rows().every(r => cells(r)[3] === 'Human'), 'only Human rows');

section('sorting');
thDate.fire('click');
check(thDate.getAttribute('data-dir') === 'asc' && cells(rows()[0])[0] <= cells(rows()[rows().length - 1])[0], 'date asc');
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
check(rows().length === 1 && count.textContent === '1 of ' + total.toLocaleString() + ' commits', 'search by SHA gives one row');
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

done();
