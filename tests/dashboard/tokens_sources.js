// tests/dashboard/tokens_sources.js
// What the token section must look like when more than one agent's logs were
// measured: one stack of bars with a measured and an estimated series per
// agent, a legend entry per agent, a subtitle naming them, and a footnote
// sentence for each. Shared by test_tokens.js (when the workspace it was
// given has several sources, as a real one can) and test_tokens_sources.js
// (always).
'use strict';

function charted(T) {
  return ((T && T.sources) || []).filter(s => s.per_day && s.per_day.length);
}

function checkSources(page, check, section) {
  const { RAW, byId, charts } = page;
  const T = RAW.summary.tokens;
  const sources = charted(T);
  const token = charts[charts.length - 1];
  const sets = token.data.datasets;
  const filter = token.options.plugins.legend.labels.filter;

  section('several sources: chart');
  check(sets.length === 2 * sources.length, 'a measured and an estimated series per source (' + sets.length + ' for ' + sources.length + ')');
  check(sets.every(d => d.stack === sets[0].stack) && token.options.scales.x.stacked === true && token.options.scales.y.stacked === true,
        'every series in one stack');
  const legend = sets.filter((d, i) => filter({ datasetIndex: i }, token.data)).map(d => d.label);
  check(legend.join('|') === sources.map(s => s.label).join('|'), 'the legend names each source once: ' + legend.join(', '));
  sources.forEach((s, i) => {
    const m = sets[2 * i], e = sets[2 * i + 1];
    check(m.data.length === s.per_day.filter(r => r[2] === 'm').length && e.data.length === s.per_day.filter(r => r[2] === 'e').length,
          s.label + ': one bar per measured and per estimated day');
    check(m.data.every(p => s.per_day.some(r => r[0] === p.x && r[1] === p.y && r[2] === 'm'))
          && e.data.every(p => s.per_day.some(r => r[0] === p.x && r[1] === p.y && r[2] === 'e')), s.label + ': the bars are its own figures');
  });
  const claude = sources.findIndex(s => s.key === 'claude-code');
  if (claude >= 0) check(sets[2 * claude].backgroundColor === 'rgba(88,166,255,0.6)', 'Claude Code keeps its blue');
  check(new Set(sources.map((s, i) => sets[2 * i].borderColor)).size === sources.length, 'each source has its own hue');

  section('several sources: text');
  const subtitle = byId('tokenChartSource').textContent;
  check(sources.every(s => subtitle.indexOf(s.label) >= 0) && / logs \u00b7 /.test(subtitle), 'the subtitle names every source: ' + subtitle);
  const note = byId('tokenNote').textContent;
  check(T.sources.every(s => note.indexOf(s.label + ': ') >= 0), 'the note has a sentence for each source');
}

module.exports = { charted, checkSources };
