// tests/dashboard/test_colours.js
// Agent colours: every agent the page draws gets a colour of its own, the
// same one on every chart and card, and only Human and Misc (and an unknown
// Claude version) are grey. First-appearance labels are filled opaquely so their
// line does not show through the text.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId, charts } = page;
const [main, , agentCum, pie, agentNet] = charts;
// The page opens in the system theme, light here; Solarized's greys there.
const theme = n => page.run('return THEME.colour(' + JSON.stringify(n) + ')');
const GREYS = ['grey', 'grey-2', 'grey-3'].map(theme);
check(theme('grey') === '#586e75' && theme('grey-2') === '#839496', 'the light greys are Solarized base01 and base0: ' + GREYS);
const NEUTRAL = ['Human', 'Misc', 'Claude (unknown version)'];
const hex = c => c.slice(0, 7).toLowerCase();   // drop the alpha suffix some charts append

section('agent colours');
const agents = Object.keys(page.run('return SEL.stats()').agents);
const pointOf = {};
RAW.commits.forEach((c, i) => { pointOf[c[4] || 'Human'] = hex(main.data.datasets[0].pointBackgroundColor[i]); });
// What the fixture was built to contain; a workspace given by
// CLOCWORK_DASH_WORKSPACE has whichever agents it has, and the checks after
// this block hold for any of them.
if (!process.env.CLOCWORK_DASH_WORKSPACE) {
  check(agents.indexOf('Copilot') >= 0 && agents.indexOf('Human') >= 0, 'fixture has Copilot and Human commits: ' + agents.join(', '));
  check(agents.indexOf('MyBot') >= 0 && !page.run('return Object.prototype.hasOwnProperty.call(AGENT_COLORS, "MyBot")'),
        'fixture has an agent with no fixed colour, so every chart below draws a fallback colour');
  check(pointOf.Copilot !== pointOf.Human, 'Copilot points differ from Human points: ' + pointOf.Copilot + ' vs ' + pointOf.Human);
}
if ('Human' in pointOf) check(pointOf.Human === '#586e75', 'Human points stay grey');
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
// Cards name the colour as a CSS variable, which the theme keeps current.
const cssVar = v => (/^var\(--c-([a-z0-9-]+)\)$/.exec(v) || [])[1];
byId('agentGrid').children.forEach(card => {
  const a = card.children[0].textContent;
  const token = cssVar(card.style['--agent']);
  check(token && theme(token) === pointOf[a], a + ': the agent card takes the colour of its points: ' + card.style['--agent']);
  check(page.root.style['--c-' + token] === pointOf[a], a + ': the variable the card names holds that colour');
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
check(colour('') === '#586e75', 'a commit with no agent is Human grey');
check(new Set(Object.values(page.run('return AGENT_COLORS')).map(theme)).size === Object.keys(page.run('return AGENT_COLORS')).length,
      'every listed agent has a colour of its own');

section('first-appearance labels');
// Solarized violet #6c71c4 at 15% over the light card surface, base3
// #fdf6e3, worked by hand:
// 0.85 * (253, 246, 227) + 0.15 * (108, 113, 196) = (231.25, 226.05, 222.35)
const first = page.run('return annotationObjects([["2026-01-01", "Opus 4.5", 0]])').first0;
check(first.label.backgroundColor === 'rgb(231,226,222)', 'label fill is the tint blended over the surface, opaque: ' + first.label.backgroundColor);
check(first.label.color === '#6c71c4' && first.borderColor === '#6c71c4', 'label text and line keep the palette colour');
const all = Object.values(main.options.plugins.annotation.annotations);
check(all.length > 0 && all.every(a => /^rgb\(/.test(a.label.backgroundColor)), 'every rendered first-appearance label is opaque');

done();
