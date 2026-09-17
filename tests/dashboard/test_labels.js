// tests/dashboard/test_labels.js
// First-appearance labels on the main chart are laid out in rows so none
// covers another, at any width and zoom; and a stat value records its length
// for the CSS that fits it to its card.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load({ variant: 'crowded' });
const { RAW, charts } = page;
const [main] = charts;
const ANN = page.run('return ANNOTATIONS');
check(ANN.length >= 12, 'the crowded variant has many first appearances: ' + ANN.length);

// A stand-in x scale: dates spread linearly over `width` pixels, as a time
// scale does, between `from` and `to` (a zoom when they are not the ends).
const day = s => Date.parse(s + 'T00:00:00Z');
function scale(width, from, to) {
  return { parse: day, getPixelForValue: v => (v - day(from)) / (day(to) - day(from)) * width };
}
// About the width of 10px bold text.
const measure = t => t.length * 6.2;
function overlaps(boxes, rows) {
  const hits = [];
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++)
      if (rows[i] === rows[j] && boxes[i].left < boxes[j].right + 4 && boxes[j].left < boxes[i].right + 4) hits.push(ANN[i][1] + '/' + ANN[j][1]);
  return hits;
}

section('rows');
const first = RAW.summary.first_date, last = RAW.summary.last_date;
const zoomFrom = ANN[3][0];
for (const [width, from, to] of [[1100, first, last], [1300, first, last], [1800, first, last], [1300, zoomFrom, last]]) {
  // page.run takes no arguments; the page's globals are the harness's.
  global.__scale = scale(width, from, to);
  global.__measure = measure;
  const boxes = global.__boxes = page.run('return labelBoxes(ANNOTATIONS, window.__scale, window.__measure)');
  const rows = page.run('return labelRows(window.__boxes)');
  const label = width + 'px from ' + from;
  check(Math.max(...rows) >= 1, label + ': the labels need more than one row');
  const hits = overlaps(boxes, rows);
  check(hits.length === 0, label + ': no label covers another' + (hits.length ? ' (' + hits.join(', ') + ')' : ''));
}
// Without the layout, the same labels would collide: the check above can fail.
global.__scale = scale(1300, first, last);
global.__boxes = page.run('return labelBoxes(ANNOTATIONS, window.__scale, window.__measure)');
check(overlaps(global.__boxes, global.__boxes.map(() => 0)).length > 0, 'in one row the labels would collide');
check(JSON.stringify(page.run('return labelRows([])')) === '[]', 'no labels, no rows');

section('the chart applies the rows');
const plugin = (main.config.plugins || []).find(p => p.id === 'labelLayout');
check(!!plugin, 'the main chart carries the label layout plugin');
const annotations = main.options.plugins.annotation.annotations;
const fakeChart = {
  options: main.options,
  scales: { x: scale(1300, first, last) },
  ctx: { font: '', save() {}, restore() {}, measureText: t => ({ width: measure(t) }) },
};
plugin.afterLayout(fakeChart);
const applied = ANN.map((a, i) => annotations['first' + i].label.yAdjust);
const expected = page.run('return labelRows(window.__boxes)').map(r => -r * page.run('return LABEL_ROW'));
check(JSON.stringify(applied) === JSON.stringify(expected), 'each label is raised by its row: ' + JSON.stringify(applied));
check(applied.some(y => y < 0), 'some labels are raised');

section('stat values');
const values = page.byId('statsGrid').children.map(c => c.children[1]);
check(values.length > 0 && values.every(v => v.style['--chars'] === String(v.textContent.length)),
      'each stat value records its length: ' + values.map(v => v.style['--chars']).join(','));

done();
