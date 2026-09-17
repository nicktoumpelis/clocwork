// tests/dashboard/test_colours.js
// Agent colours: every agent the page draws gets a colour of its own, the
// same one on every chart, and only Human and Misc (and an unknown Claude
// version) are grey. First-appearance labels are filled opaquely so their
// line does not show through the text.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId, charts } = page;
const [main, , agentCum, pie, agentNet] = charts;
const GREYS = ['#8b949e', '#6e7681', '#484f58'];
const NEUTRAL = ['Human', 'Misc', 'Claude (unknown version)'];
const hex = c => c.slice(0, 7).toLowerCase();   // drop the alpha suffix some charts append

section('agent colours');
const agents = Object.keys(page.run('return SEL.stats()').agents);
check(agents.indexOf('Copilot') >= 0 && agents.indexOf('Human') >= 0, 'fixture has Copilot and Human commits: ' + agents.join(', '));
check(agents.indexOf('MyBot') >= 0 && !page.run('return Object.prototype.hasOwnProperty.call(AGENT_COLORS, "MyBot")'),
      'fixture has an agent with no fixed colour, so every chart below draws a fallback colour');
const pointOf = {};
RAW.commits.forEach((c, i) => { pointOf[c[4] || 'Human'] = hex(main.data.datasets[0].pointBackgroundColor[i]); });
check(pointOf.Copilot !== pointOf.Human, 'Copilot points differ from Human points: ' + pointOf.Copilot + ' vs ' + pointOf.Human);
check(pointOf.Human === '#8b949e', 'Human points stay grey');
agents.filter(a => NEUTRAL.indexOf(a) < 0).forEach(a => {
  check(GREYS.indexOf(pointOf[a]) < 0, a + ' is not grey on the main chart: ' + pointOf[a]);
});
agentCum.data.datasets.forEach(d => {
  check(hex(d.borderColor) === pointOf[d.label], d.label + ': cumulative line matches its main-chart points (' + d.borderColor + ')');
});
pie.data.labels.forEach((a, i) => {
  check(hex(pie.data.datasets[0].backgroundColor[i]) === pointOf[a], a + ': doughnut slice matches its main-chart points');
});
const netColours = agentNet.data.datasets[0].backgroundColor;
agentNet.data.labels.forEach((a, i) => {
  check(hex(Array.isArray(netColours) ? netColours[i] : netColours) === pointOf[a], a + ': net bar matches its main-chart points');
});
byId('agentGrid').children.forEach(card => {
  const a = card.children[0].textContent;
  check(hex(card.style.borderLeftColor) === pointOf[a] && hex(card.children[0].style.color) === pointOf[a], a + ': agent card border and name match');
});

section('agents without a fixed colour');
const colour = n => page.run('return agentColour(' + JSON.stringify(n) + ')');
['Claude Opus 9', 'MyBot', 'Roo', 'constructor'].forEach(n => {
  check(/^#[0-9a-f]{6}$/i.test(colour(n)) && GREYS.indexOf(hex(colour(n))) < 0, n + ' gets a non-grey colour: ' + colour(n));
  check(colour(n) === colour(n), n + ' gets the same colour every time');
});
check(new Set(['Claude Opus 9', 'MyBot', 'Roo', 'Cline', 'Kilo'].map(colour)).size > 1, 'unlisted agents do not all share one colour');
['Copilot', 'Cursor', 'Codex', 'Devin', 'aider', 'Gemini Code Assist', 'Gemini'].forEach(n => {
  check(page.run('return Object.prototype.hasOwnProperty.call(AGENT_COLORS, ' + JSON.stringify(n) + ')'), n + ' has a fixed colour');
});
check(colour('') === '#8b949e', 'a commit with no agent is Human grey');

section('first-appearance labels');
// #d2a8ff at 15% over the card surface #161b22, worked by hand:
// 0.85 * (22, 27, 34) + 0.15 * (210, 168, 255) = (50.2, 48.15, 67.15)
const first = page.run('return annotationObjects([["2026-01-01", "Opus 4.5", 0]])').first0;
check(first.label.backgroundColor === 'rgb(50,48,67)', 'label fill is the tint blended over the surface, opaque: ' + first.label.backgroundColor);
check(first.label.color === '#d2a8ff' && first.borderColor === '#d2a8ff', 'label text and line keep the palette colour');
const all = Object.values(main.options.plugins.annotation.annotations);
check(all.length > 0 && all.every(a => /^rgb\(/.test(a.label.backgroundColor)), 'every rendered first-appearance label is opaque');

done();
