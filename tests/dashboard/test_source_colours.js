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

function colours(page) {
  const token = page.charts[page.charts.length - 1];
  const keys = page.RAW.summary.tokens.sources.filter(s => s.per_day && s.per_day.length).map(s => s.key);
  const out = {};
  keys.forEach((k, i) => { out[k] = token.data.datasets[2 * i].borderColor; });
  return out;
}

['opencode', 'copilot', 'kilo'].forEach(key => {
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

section('an agent this version does not know still gets a colour');
const unknown = colours(load({ variant: 'sources', raw: as('some-future-agent', 'Future') }));
check(typeof unknown['some-future-agent'] === 'string' && /^#[0-9a-f]{6}$/i.test(unknown['some-future-agent']),
      'from the palette: ' + unknown['some-future-agent']);

done();
