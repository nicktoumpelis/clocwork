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
const area = width => ({ left: 0, right: width, top: 0, bottom: 400 });
const GAP = page.run('return LABEL_GAP');
function overlaps(boxes, rows) {
  const hits = [];
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++)
      if (!boxes[i].hidden && !boxes[j].hidden && rows[i] === rows[j] && boxes[i].left < boxes[j].right + GAP && boxes[j].left < boxes[i].right + GAP) hits.push(i + '/' + j);
  return hits;
}

section('rows');
const first = RAW.summary.first_date, last = RAW.summary.last_date;
const zoomFrom = ANN[3][0];
for (const [width, from, to] of [[1100, first, last], [1300, first, last], [1800, first, last], [1300, zoomFrom, last]]) {
  // page.run takes no arguments; the page's globals are the harness's.
  global.__scale = scale(width, from, to);
  global.__measure = measure;
  global.__area = area(width);
  const boxes = global.__boxes = page.run('return labelBoxes(ANNOTATIONS, window.__scale, window.__measure, window.__area)');
  const rows = page.run('return labelRows(window.__boxes)');
  const label = width + 'px from ' + from;
  check(Math.max(...rows) >= 1, label + ': the labels need more than one row');
  const hits = overlaps(boxes, rows);
  check(hits.length === 0, label + ': no label covers another' + (hits.length ? ' (' + hits.join(', ') + ')' : ''));
}
// Boxes in any order get the same rows as in date order.
const reversed = global.__boxes.slice().reverse();
global.__reversed = reversed;
const reversedRows = page.run('return labelRows(window.__reversed)');
check(overlaps(reversed, reversedRows).length === 0 && JSON.stringify(reversedRows.slice().reverse()) === JSON.stringify(page.run('return labelRows(window.__boxes)')),
      'labels given in reverse order get the same rows');
// Without the layout, the same labels would collide: the check above can fail.
global.__scale = scale(1300, first, last);
global.__area = area(1300);
global.__boxes = page.run('return labelBoxes(ANNOTATIONS, window.__scale, window.__measure, window.__area)');
check(overlaps(global.__boxes, global.__boxes.map(() => 0)).length > 0, 'in one row the labels would collide');
// A box is its text's width plus the padding, centred on the label's date.
const pad = page.run('return LABEL_PAD_X');
const box = global.__boxes[5], x = global.__scale.getPixelForValue(day(ANN[5][0]));
check(Math.abs(box.right - box.left - (measure(ANN[5][1]) + 2 * pad)) < 1e-9 && Math.abs((box.left + box.right) / 2 - x) < 1e-9,
      'a box spans its text and padding around its date: ' + JSON.stringify(box));
check(JSON.stringify(page.run('return labelRows([])')) === '[]', 'no labels, no rows');

section('edges, hidden labels and short charts');
// The annotation plugin moves a label near an edge inside the chart area,
// keeping its padding clear; the boxes follow it.
global.__edge = { parse: day, getPixelForValue: v => v === day('2025-01-01') ? 3 : v === day('2025-01-02') ? 297 : 40 };
const edge = page.run("return labelBoxes([['2025-01-01', 'Left'], ['2025-01-02', 'Right'], ['2025-01-03', 'A label far too wide for an area of three hundred pixels to hold']], window.__edge, window.__measure, {left: 0, right: 300})");
check(Math.abs(edge[0].left - pad) < 1e-9, 'a label at the left edge starts its padding inside: ' + edge[0].left);
check(Math.abs(edge[1].right - (300 - pad)) < 1e-9, 'a label at the right edge ends its padding inside: ' + edge[1].right);
check(Math.abs((edge[2].left + edge[2].right) / 2 - 150) < 1e-9 && edge[2].right - edge[2].left > 300, 'a label wider than the area is centred on it');
global.__clamped = [{ left: 0, right: 50 }, { left: 30, right: 80 }];
check(JSON.stringify(page.run('return labelRows(window.__clamped)')) === '[0,1]', 'labels moved to overlap go in different rows');
// A label whose line is outside the chart (zoomed away) takes no room.
global.__hidden = [{ left: -40, right: 60, hidden: true }, { left: 10, right: 90 }];
check(JSON.stringify(page.run('return labelRows(window.__hidden)')) === '[0,0]', 'a hidden label leaves its row free');
check(page.run("return labelBoxes([['2025-01-01', 'Gone']], window.__edge, window.__measure, {left: 10, right: 300})")[0].hidden === true,
      'a label whose line is left of the area is hidden');
// Rows stop at the chart's height; a label with no free row shares the one
// whose last label ends first.
global.__stack = [{ left: 0, right: 100 }, { left: 10, right: 30 }, { left: 20, right: 200 }, { left: 40, right: 60 }];
const capped = page.run('return labelRows(window.__stack, 2)');
check(JSON.stringify(capped) === '[0,1,1,0]' || JSON.stringify(capped) === '[0,1,1,1]',
      'rows stop at the cap: ' + JSON.stringify(capped));
check(Math.max(...capped) <= 1, 'no row beyond the cap');
check(JSON.stringify(page.run('return labelRows(window.__stack)')) === '[0,1,2,1]', 'without a cap the same labels take three rows');

section('the chart applies the rows');
const plugin = (main.config.plugins || []).find(p => p.id === 'labelLayout');
check(!!plugin, 'the main chart carries the label layout plugin');
const annotations = main.options.plugins.annotation.annotations;
const fakeChart = {
  options: main.options,
  scales: { x: scale(1300, first, last) },
  chartArea: area(1300),
  ctx: { font: '', save() {}, restore() {}, measureText: t => ({ width: measure(t) }) },
};
plugin.afterLayout(fakeChart);
const applied = ANN.map((a, i) => annotations['first' + i].label.yAdjust);
// The rows these labels take at 1300px, 20px apart.
const expected = [0, -20, -40, 0, -20, -40, 0, -20, 0, -40, 0, -20, -60, 0, -20];
check(JSON.stringify(applied) === JSON.stringify(expected), 'each label is raised by its row: ' + JSON.stringify(applied));
check(applied.some(y => y < 0), 'some labels are raised');

section('stat values');
const values = page.byId('statsGrid').children.map(c => c.children[1]);
check(values.length > 0 && values.every(v => v.style['--chars'] === String(v.textContent.length)),
      'each stat value records its length: ' + values.map(v => v.style['--chars']).join(','));

done();
