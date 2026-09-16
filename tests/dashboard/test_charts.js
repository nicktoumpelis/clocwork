// tests/dashboard/test_charts.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId, charts } = page;
const LANGS = RAW.languages;
const hasTokens = !!(RAW.summary.tokens && RAW.summary.tokens.per_day && RAW.summary.tokens.per_day.length);   // the page shows no token element without data
const fmt = n => new Intl.NumberFormat('en-US').format(n);
const enDate = iso => { const p = iso.split('-').map(Number); return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(p[0], p[1] - 1, p[2])); };
const [main, daily, agentCum, pie, agentNet] = charts;
const card = label => { const c = byId('statsGrid').children.find(x => x.children[0].textContent === label); return c && c.children[1].textContent; };

section('initial render');
let st = page.run('return SEL.stats()');
check(charts.length === (hasTokens ? 6 : 5), (hasTokens ? 'six' : 'five') + ' charts created');
check(main.data.datasets[0].label === 'Code Lines' && main.data.datasets[0].data.length === RAW.commits.length, 'main dataset labelled and sized');
check(main.data.datasets[1].label === 'Tests' && main.data.datasets[1].hidden === true, 'tests dataset present but hidden');
check(main.data.datasets[0].data[RAW.commits.length - 1].y === st.cumulative[RAW.commits.length - 1], 'main series ends at final cumulative');
check(byId('mainChartTitle').textContent === 'Code Lines Over Time', 'main title');
check(daily.data.datasets[0].data.length === st.daily.length, 'daily bars match daily series');
check(pie.data.datasets[0].data.reduce((a, b) => a + b, 0) === RAW.commits.length, 'pie sums to total commits');
check(agentNet.data.labels.every((a, i) => i === 0 || st.agents[agentNet.data.labels[i - 1]].net >= st.agents[a].net), 'agent net bars sorted by net');
check(card('Lines at HEAD') === fmt(page.run('return SEL.headTotal(false)')), 'Lines at HEAD card');
check(card('Peak') === fmt(st.peak.value) && card('Peak Date') === enDate(st.peak.date), 'peak cards');
check(byId('agentGrid').children.length === Object.keys(st.agents).length, 'one agent card per agent');
check(byId('reconNote').hidden === (page.run('return SEL.drift()') === 0), 'reconciliation note only when drift');

section('after selecting ' + LANGS[0] + ' / comment');
page.run('SEL.set({ lang: "' + LANGS[0] + '", type: "comment" })');
st = page.run('return SEL.stats()');
check(main.updates >= 1 && daily.updates >= 1 && agentCum.updates >= 1 && agentNet.updates >= 1, 'charts updated');
check(main.data.datasets[0].label === LANGS[0] + ' Comment Lines' && byId('mainChartTitle').textContent === LANGS[0] + ' Comment Lines Over Time', 'main relabelled');
check(main.data.datasets[0].data[RAW.commits.length - 1].y === st.cumulative[RAW.commits.length - 1], 'main series recomputed');
check(main.options.scales.y.title.text === LANGS[0] + ' Comment Lines', 'y axis relabelled');
check(byId('dailyChartTitle').textContent === 'Daily ' + LANGS[0] + ' Comment Lines Change', 'daily title');
check(daily.data.datasets[0].data.every((d, i) => d.y === st.daily[i].net), 'daily bars recomputed');
check(daily.options.scales.y.title.text === LANGS[0] + ' Comment Lines Change', 'daily y axis title follows the selection');
check(pie.updates === 0, 'pie chart does not re-render on selection change');
const cumLabels = agentCum.data.datasets.map(d => d.label);
check(cumLabels.every(a => st.agents[a].net !== 0) && cumLabels.every((a, i) => i === 0 || st.agents[cumLabels[i - 1]].net >= st.agents[a].net), 'agent cumulative datasets: non-zero, net desc');
check(agentNet.data.datasets[0].data.every((v, i) => v === st.agents[agentNet.data.labels[i]].added), 'agent net added bars recomputed');
check(byId('agentNetTitle').textContent === 'Net ' + LANGS[0] + ' Comment Lines by Agent', 'agent net title');
check(card('Lines at HEAD') === fmt(page.run('return SEL.headTotal(false)')) && card('Peak') === fmt(st.peak.value), 'cards recomputed');
const firstCard = byId('agentGrid').children[0];
check(firstCard.children[1].children[1].children[0].textContent === '+' + fmt(st.agents[firstCard.children[0].textContent].added) + ' ' + LANGS[0] + ' Comment LOC', 'agent card added line uses selection label');

section('tests toggle');
const toggle = byId('testsToggle');
toggle.fire('click');
check(page.run('return SEL.get().tests') === true && main.data.datasets[1].hidden === false, 'toggle shows the tests line');
check(main.data.datasets[1].data[RAW.commits.length - 1].y === st.testCumulative[RAW.commits.length - 1], 'tests series is the test cumulative');
check(toggle.className.indexOf('active') >= 0, 'toggle highlighted');
toggle.fire('click');
check(main.data.datasets[1].hidden === true, 'toggle hides again');

done();
