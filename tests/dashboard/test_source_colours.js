// tests/dashboard/test_source_colours.js
// A source's hue in the token chart belongs to the source, not to its place
// in the list: the same agent keeps its colour whichever other agents have
// logs beside it, so the chart reads the same across runs (#68).
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

// The sources variant charts Claude Code, Codex CLI and Gemini CLI. Relabel
// its third source as another agent, then chart it with and without Codex.
function as(key, label, dropCodex) {
  return RAW => {
    const list = RAW.summary.tokens.sources;
    const third = list[2];
    third.key = key; third.label = label;
    if (dropCodex) RAW.summary.tokens.sources = list.filter(s => s.key !== 'codex');
  };
}

// Each charted source's measured series colour, by key. The page charts the
// sources in the blob's order, a measured and an estimated series apiece; the
// label check makes a reordering fail here rather than pin a colour on the
// wrong source.
function colours(page) {
  const token = page.charts[page.charts.length - 1];
  const charted = page.RAW.summary.tokens.sources.filter(s => s.per_day && s.per_day.length);
  const out = {};
  charted.forEach((s, i) => {
    const series = token.data.datasets[2 * i];
    check(series.label === s.label, 'series ' + 2 * i + ' is ' + s.label + ' (' + series.label + ')');
    out[s.key] = series.borderColor;
  });
  return out;
}

['opencode', 'copilot', 'kilo', 'qwen'].forEach(key => {
  section('a source keeps its colour: ' + key);
  const three = colours(load({ variant: 'sources', raw: as(key, key) }));
  const two = colours(load({ variant: 'sources', raw: as(key, key, true) }));
  check(Object.keys(three).length === 3 && Object.keys(two).length === 2,
        'sanity: charted with three sources, then two (' + Object.keys(three) + ' / ' + Object.keys(two) + ')');
  check(typeof three[key] === 'string' && three[key].length > 0, 'it has a colour: ' + three[key]);
  check(three[key] === two[key], 'the same with Codex beside it as without (' + three[key] + ' / ' + two[key] + ')');
  // On the palette fallback this failed as well: with Codex gone the source
  // moved to the palette's second hue, which is Claude Code's own blue.
  [three, two].forEach(chart => check(Object.keys(chart).filter(k => k !== key).every(k => chart[k] !== chart[key]),
        'and it is not the colour of a source beside it (' + Object.keys(chart).length + ' charted)'));
});

section('an agent this version does not know');
// Beside Claude Code alone it is second in the list, which on the palette by
// position is blue: Claude Code's own.
const withCodex = load({ variant: 'sources', raw: as('some-future-agent', 'Future') });
const alone = load({ variant: 'sources', raw: as('some-future-agent', 'Future', true) });
const known = withCodex.run('return Object.keys(SOURCE_COLOURS).map(function(k) { return themeColour(SOURCE_COLOURS[k]); })');
const [three, two] = [colours(withCodex), colours(alone)];
const future = two['some-future-agent'];
check(typeof future === 'string' && /^#[0-9a-f]{6}$/i.test(future), 'still gets a colour: ' + future);
check(known.length === 7 && known.indexOf(future) < 0, 'and it is no known source\'s (' + future + ' against ' + known.join(' ') + ')');
check(three['some-future-agent'] === future, 'and it does not move when Codex joins (' + three['some-future-agent'] + ' / ' + future + ')');
// Nor a shade of one: the first stranger takes a hue family no known source uses.
const family = t => t.split('-')[0];
const taken = withCodex.run('return Object.keys(SOURCE_COLOURS).map(function(k) { return SOURCE_COLOURS[k]; })').map(family);
const first = withCodex.run('return SOURCE_SPARE[0]');
check(taken.indexOf(family(first)) < 0, 'and its hue family is its own (' + first + ', beside ' + taken.join(' ') + ')');

done();
