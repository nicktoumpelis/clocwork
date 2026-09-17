// tests/dashboard/test_theme.js
// Light, dark and system themes: which one a page opens in, the switch that
// changes it, what is kept in the browser, and that every colour on the page
// follows. The expected colours are Solarized's published values, not the
// page's own tables.
'use strict';
const fs = require('fs');
const path = require('path');
const { load } = require('./harness');
const { check, section, done } = require('./check');

const SOL = {
  base03: '#002b36', base02: '#073642', base01: '#586e75', base00: '#657b83',
  base0: '#839496', base1: '#93a1a1', base2: '#eee8d5', base3: '#fdf6e3',
  yellow: '#b58900', orange: '#cb4b16', red: '#dc322f', magenta: '#d33682',
  violet: '#6c71c4', blue: '#268bd2', cyan: '#2aa198', green: '#859900',
};
const KEY = 'clocwork-theme';
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
// WCAG 2 contrast ratio.
function contrast(a, b) {
  const lum = h => {
    const [r, g, bl] = rgb(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
// `a` moved `t` of the way to `b`, worked here rather than taken from the page.
const mix = (a, b, t) => '#' + rgb(a).map((v, i) => Math.round(v * (1 - t) + rgb(b)[i] * t).toString(16).padStart(2, '0')).join('');
const attr = page => page.root.getAttribute('data-theme');
const colour = (page, n) => page.run('return THEME.colour(' + JSON.stringify(n) + ')');

section('the theme a page opens in');
let page = load();
check(page.run('return THEME.choice()') === 'system' && attr(page) === 'light', 'with nothing stored, a light system gives the light theme');
check(page.root.style['--surface'] === SOL.base3 && page.root.style['--text'] === SOL.base02, 'light cards are base3, light text base02');
check(page.root.style['color-scheme'] === 'light', 'the browser is told the scheme, for its own controls');
page = load({ prefersDark: true });
check(attr(page) === 'dark' && page.root.style['--bg'] === SOL.base03 && page.root.style['--surface'] === SOL.base02,
      'a dark system gives the dark theme: base03 page, base02 cards');
page = load({ prefersDark: true, storage: { [KEY]: 'light' } });
check(page.run('return THEME.choice()') === 'light' && attr(page) === 'light', 'a stored choice wins over the system');
page = load({ storage: { [KEY]: 'sepia' } });
check(page.run('return THEME.choice()') === 'system', 'an unknown stored value is ignored');
page = load({ prefersDark: true, storage: 'refuse' });
check(attr(page) === 'dark', 'storage that refuses leaves the system theme');
page.run("THEME.set('light')");
check(attr(page) === 'light', 'and the switch still works for this page');

section('the switch');
page = load({ storage: {} });
const box = page.byId('themeSwitch');
const buttons = box.children;
check(buttons.map(b => b.getAttribute('data-choice')).join() === 'light,system,dark', 'three buttons: light, system, dark');
check(buttons.every(b => b.getAttribute('role') === 'radio' && b.getAttribute('aria-label') && /<svg/.test(b.innerHTML)),
      'each is a labelled radio with an icon');
const checked = () => buttons.filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.getAttribute('data-choice'));
check(checked().join() === 'system' && buttons.map(b => b.tabIndex).join() === '-1,0,-1', 'system is checked, and the only one in the tab order');
check(buttons[1].title === 'Match the system (light now)', 'the system button says what the system is: ' + buttons[1].title);

const [main, daily, agentCum, pie, net, token] = page.charts;
const updates = page.charts.map(c => c.updates);
const before = {
  tooltip: main.options.plugins.tooltip.backgroundColor, grid: main.options.scales.y.grid.color,
  pie: pie.data.datasets[0].borderColor, label: main.options.plugins.annotation.annotations.first0.label.backgroundColor,
  cum: agentCum.data.datasets.map(d => d.borderColor).join(), defaults: page.run('return Chart.defaults.color'),
};
buttons[2].fire('click');
check(attr(page) === 'dark' && page.store[KEY] === 'dark' && checked().join() === 'dark', 'a click on dark applies it, keeps it and checks it');
check(page.charts.every((c, i) => c.updates > updates[i]), 'every chart is redrawn');
check(page.root.style['--bg'] === SOL.base03 && page.root.style['--text'] === SOL.base2, 'the page colours are the dark ones');
check(main.options.plugins.tooltip.backgroundColor !== before.tooltip && main.options.scales.y.grid.color !== before.grid
      && daily.options.plugins.tooltip.titleColor === SOL.base2 && token.options.scales.y.title.color === SOL.base1,
      'tooltips and axes take the dark colours');
check(before.defaults === SOL.base01 && page.run('return Chart.defaults.color') === SOL.base1, 'so do the chart defaults, for legends and ticks');
check(before.pie === SOL.base3 && pie.data.datasets[0].borderColor === SOL.base02, 'doughnut slices are parted by the card colour');
const opus = page.RAW.commits.findIndex(c => c[4] === 'Claude Opus 4.6');
check(opus >= 0 && main.data.datasets[0].pointBackgroundColor[opus] === SOL.blue, 'Opus 4.6 points are Solarized blue');
check(main.options.plugins.annotation.annotations.first0.label.backgroundColor !== before.label, 'first-appearance labels are blended over the dark card');
// The second tones in dark are 35% of the way to base3; Human is base1.
const lineOf = l => (agentCum.data.datasets.find(d => d.label === l) || {}).borderColor;
check(before.cum !== agentCum.data.datasets.map(d => d.borderColor).join()
      && lineOf('Claude Fable 5.1') === mix(SOL.yellow, SOL.base3, 0.35) && lineOf('Copilot') === mix(SOL.violet, SOL.base3, 0.35)
      && lineOf('Human') === SOL.base1,
      'agent lines are coloured again: ' + agentCum.data.datasets.map(d => d.label + ' ' + d.borderColor).join(', '));
check(net.data.datasets[1].backgroundColor === 'rgba(' + rgb(colour(page, 'danger')).join(',') + ',0.4)', 'deleted bars take the dark red');
// A badge and a card name the colour through a variable, which now holds the dark tone.
check(page.root.style['--c-blue-2'] === mix(SOL.blue, SOL.base3, 0.35), 'series variables hold the dark tones: ' + page.root.style['--c-blue-2']);

// The arrow keys move the choice, and focus with it.
buttons[2].fire('keydown', { key: 'ArrowRight', preventDefault() {} });
check(page.run('return THEME.choice()') === 'light' && page.run('return document.activeElement') === buttons[0], 'the right arrow wraps from dark to light');
buttons[0].fire('keydown', { key: 'ArrowRight', preventDefault() {} });
check(page.run('return THEME.choice()') === 'system' && page.store[KEY] === 'system', 'and moves on to system');

section('following the system');
page.media.set(true);
check(attr(page) === 'dark' && page.byId('themeSwitch').children[1].title === 'Match the system (dark now)', 'on system, the page follows the OS turning dark');
page.media.set(false);
check(attr(page) === 'light', 'and back');
page.run("THEME.set('light')");
const quiet = page.charts.map(c => c.updates);
page.media.set(true);
check(attr(page) === 'light' && page.charts.every((c, i) => c.updates === quiet[i]), 'a fixed choice ignores the OS, without even a redraw');

section('contrast');
for (const name of ['light', 'dark']) {
  const c = page.run('return themeColours(' + JSON.stringify(name) + ')');
  for (const role of ['text', 'text-muted', 'accent', 'success', 'danger']) {
    for (const under of ['bg', 'surface']) {
      const r = contrast(c[role], c[under]);
      check(r >= 4.5, name + ': ' + role + ' on ' + under + ' reads at ' + r.toFixed(2) + ':1');
    }
  }
  // Chart series: every agent and every first-appearance line has a colour of its own.
  const agents = page.run('return AGENT_COLORS');
  const series = Object.keys(agents).map(a => c[agents[a]]);
  check(series.every(Boolean) && new Set(series).size === series.length, name + ': ' + series.length + ' agent colours, all different');
  // Badge and card text: the agent colour with 40% of the text colour mixed in.
  const faint = Object.keys(agents).filter(a => contrast(mix(c[agents[a]], c.text, 0.4), c.surface) < 4.5);
  check(faint.length === 0, name + ': every agent name reads at 4.5:1 on a card' + (faint.length ? ': not ' + faint.join(', ') : ''));
  const spare = page.run('return AGENT_FALLBACK_PALETTE').map(t => c[t]);
  check(spare.every(Boolean) && new Set(spare).size === spare.length && spare.every(x => series.indexOf(x) < 0),
        name + ': colours for unlisted agents are their own, not a listed agent\'s');
  const lines = page.run('return ANNOTATION_PALETTE').map(t => c[t]);
  check(lines.every(Boolean) && new Set(lines).size === lines.length, name + ': first-appearance colours all different');
  check(c.blue === SOL.blue && c.yellow === SOL.yellow && c.violet === SOL.violet, name + ': the accents are Solarized\'s own');
}

section('the stylesheet names only colours the theme sets');
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'clocwork', 'template.html'), 'utf8');
const css = html.slice(html.indexOf('<style>'), html.indexOf('</style>')).replace(/\/\*[\s\S]*?\*\//g, '');
const used = new Set((css.match(/var\(--[a-z0-9-]+/g) || []).map(v => v.slice(6)));
const set = new Set(Object.keys(page.root.style).filter(k => k.startsWith('--')).map(k => k.slice(2)));
const own = ['chars', 'row-height', 'agent'];   // set per element by the page, not by the theme
check(/color-mix\(in srgb, var\(--agent, var\(--accent\)\) 60%, var\(--text\)\)/.test(css), 'agent text mixes 40% of the text colour in, as the check above assumes');
const missing = [...used].filter(v => !set.has(v) && own.indexOf(v) < 0);
check(used.size > 5 && missing.length === 0, 'every var() the stylesheet reads is set: ' + (missing.join(', ') || [...used].join(', ')));
check(!/#[0-9a-f]{6}\b|rgba?\(/i.test(css), 'no colour is written into the stylesheet');

done();
