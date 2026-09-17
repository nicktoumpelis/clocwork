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
check(JSON.stringify(page.run('return labelRows(window.__clamped)')) === '[1,0]', 'labels moved to overlap go in different rows, the later lower');
// Labels moved inside at the right edge share it: the later line keeps the row.
global.__atRight = [{ left: 200, right: 294, x: 290 }, { left: 200, right: 294, x: 299 }];
check(JSON.stringify(page.run('return labelRows(window.__atRight, 1)')) === '[0,0]'
      && JSON.stringify(global.__atRight.map(b => b.dropped)) === '[true,false]',
      'of two labels at the right edge, the later one is kept');
// A label whose line is outside the chart (zoomed away) takes no room.
global.__hidden = [{ left: -40, right: 60, hidden: true }, { left: 10, right: 90 }];
check(JSON.stringify(page.run('return labelRows(window.__hidden)')) === '[0,0]', 'a hidden label leaves its row free');
check(page.run("return labelBoxes([['2025-01-01', 'Gone']], window.__edge, window.__measure, {left: 10, right: 300})")[0].hidden === true,
      'a label whose line is left of the area is hidden');
check(page.run("return labelBoxes([['2025-01-02', 'Gone']], window.__edge, window.__measure, {left: 0, right: 290})")[0].hidden === true,
      'a label whose line is right of the area is hidden');
// Rows stop at the chart's height. Labels are placed from the right, so
// the latest keep their rows. A label with no free row and no short form is
// left off: C here, which leaves D a free row 1.
global.__stack = [{ left: 100, right: 200 }, { left: 170, right: 190 }, { left: 0, right: 180 }, { left: 140, right: 160 }];
const capped = page.run('return labelRows(window.__stack, 2)');
check(JSON.stringify(capped) === '[0,1,0,1]', 'rows stop at the cap: ' + JSON.stringify(capped));
check(JSON.stringify(global.__stack.map(b => b.dropped)) === '[false,false,true,false]', 'the label with no room is left off');
check(JSON.stringify(page.run('return labelRows(window.__stack)')) === '[0,1,2,1]', 'without a cap the same labels take three rows');
// A shortened label's row starts where its short form starts: the next
// label to the left fits before it, though not before the full label.
global.__afterShort = [{ left: 90, right: 140 }, { left: 0, right: 100, short: { left: 50, right: 84 } }, { left: 10, right: 40 }];
check(JSON.stringify(page.run('return labelRows(window.__afterShort, 1)')) === '[0,0,0]'
      && JSON.stringify(global.__afterShort.map(b => b.dropped)) === '[false,false,false]',
      'a row starts where its shortened label starts');
// A label whose short form fits a free row takes it, shortened.
global.__shorter = [{ left: 50, right: 100 }, { left: 0, right: 60, short: { left: 10, right: 44 } }];
check(JSON.stringify(page.run('return labelRows(window.__shorter, 1)')) === '[0,0]'
      && JSON.stringify(global.__shorter.map(b => [b.shortened, b.dropped])) === '[[false,false],[true,false]]',
      'a label that fits only in its short form is shortened');
// One whose short form fits nowhere either is left off, and one that fits in
// full is not shortened.
global.__noroom = [{ left: 110, right: 160 }, { left: 60, right: 120, short: { left: 70, right: 110 } }, { left: 0, right: 40, short: { left: 10, right: 30 } }];
page.run('return labelRows(window.__noroom, 1)');
check(JSON.stringify(global.__noroom.map(b => [b.shortened, b.dropped])) === '[[false,false],[true,true],[false,false]]',
      'a label with no room even when short is left off, and a room-full label stays whole: ' + JSON.stringify(global.__noroom.map(b => [b.shortened, b.dropped])));

section('short forms');
for (const [full, short] of [['Opus 4.8 (1M)', 'O4.8 (1M)'], ['Sonnet 5', 'S5'], ['Opus 4.6 + Fable 5.1', 'O4.6 + F5.1'],
                             ['Gemini Code Assist', 'Gemini Code Assist'], ['Copilot', 'Copilot'], ['(unknown version)', '(unknown version)'],
                             ['MyBot + Opus 5', 'MyBot + O5']]) {
  global.__text = full;
  check(page.run('return shortLabel(window.__text)') === short, full + ' -> ' + short);
}
global.__named = [['2025-01-01', 'Opus 4.8 (1M)'], ['2025-01-02', 'Copilot']];
const named = page.run("return labelBoxes(window.__named, window.__edge, window.__measure, {left: 0, right: 300})");
check(named[0].short && Math.abs(named[0].short.right - named[0].short.left - (measure('O4.8 (1M)') + 2 * pad)) < 1e-9, 'a box carries its short form\'s box');
check(named[1].short === null, 'a label with nothing to shorten has no short box');
// A short form near an edge is moved inside like the full label.
global.__atEdge = [['2025-01-01', 'Opus 4.8 (1M)']];
const atEdge = page.run("return labelBoxes(window.__atEdge, window.__edge, window.__measure, {left: 0, right: 300})")[0];
check(Math.abs(atEdge.short.left - pad) < 1e-9, 'a short form at the left edge starts its padding inside: ' + atEdge.short.left);

// A short form two labels share would not say which is which.
global.__twins = [['2025-01-01', 'Opus 5'], ['2025-01-02', 'Omni 5'], ['2025-01-03', 'Sonnet 5']];
const twins = page.run("return labelBoxes(window.__twins, window.__edge, window.__measure, {left: 0, right: 300})");
check(twins[0].short === null && twins[1].short === null && twins[2].short !== null,
      'labels that would share a short form keep their full text, and others still shorten');

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
const expected = [0, -40, -20, 0, -20, -40, 0, -20, 0, -60, -40, 0, -20, -40, 0];
check(JSON.stringify(applied) === JSON.stringify(expected), 'each label is raised by its row: ' + JSON.stringify(applied));
check(applied.some(y => y < 0), 'some labels are raised');
// The top row may use the canvas above the area: an area whose foot is 45px
// down has room for two rows (the upper one's top edge 21 + 20 = 41px up).
fakeChart.chartArea = { left: 0, right: 1300, top: 30, bottom: 45 };
plugin.afterLayout(fakeChart);
const short = ANN.map((a, i) => annotations['first' + i].label.yAdjust);
check(short.every(y => y === 0 || y === -20) && short.some(y => y === -20), 'a short chart gets two rows: ' + JSON.stringify(short));
const shown = ANN.map((a, i) => annotations['first' + i].label.display);
const texts = ANN.map((a, i) => annotations['first' + i].label.content);
check(shown.includes(false), 'labels with no room are not drawn: ' + JSON.stringify(shown));
check(texts.some((t, i) => t !== ANN[i][1]) && texts.every((t, i) => t === ANN[i][1] || t === page.run('return shortLabel(ANNOTATIONS[' + i + '][1])')),
      'some labels are shortened, and each shows its full or short form: ' + JSON.stringify(texts));
// On a narrow, short chart the labels left off give way to those further
// right: the two newest are drawn, and each label left off meets a drawn one
// that ends further right (an early long label can end past a later short one).
fakeChart.scales = { x: scale(360, first, last) };
fakeChart.chartArea = { left: 0, right: 360, top: 30, bottom: 45 };
plugin.afterLayout(fakeChart);
const drawn = ANN.map((a, i) => annotations['first' + i].label.display);
const drawnAt = drawn.map((d, i) => d ? i : -1).filter(i => i >= 0), droppedAt = drawn.map((d, i) => d ? -1 : i).filter(i => i >= 0);
global.__scale = fakeChart.scales.x;
global.__area = fakeChart.chartArea;
const narrow = page.run('return labelBoxes(ANNOTATIONS, window.__scale, window.__measure, window.__area)');
const meets = (a, b) => a.left < b.right + GAP && b.left < a.right + GAP;
check(droppedAt.every(i => annotations['first' + i].label.content === ANN[i][1]),
      'a label left off keeps its full name for the hover');
check(drawn[ANN.length - 1] && drawn[ANN.length - 2] && droppedAt.length > 0,
      'at 360px the two newest labels are drawn: ' + JSON.stringify(drawnAt));
check(droppedAt.every(i => drawnAt.some(j => narrow[j].right >= narrow[i].right && meets(narrow[i], narrow[j]))),
      'each label left off gives way to one further right: ' + JSON.stringify(droppedAt));
// A left-off label shows while the pointer is at its line, and after a tap.
const gone = droppedAt[0], kept = drawnAt[0];
const element = { label: { options: { display: false, z: 0 } } };
const hook = (i, name) => annotations['first' + i][name];
check(hook(gone, 'enter')({ element }) === true && element.label.options.display === true && element.label.options.z > 0,
      'a left-off label shows on hover, over the labels in its row');
check(hook(gone, 'leave')({ element }) === true && element.label.options.display === false && element.label.options.z === 0,
      'and hides again when the pointer leaves');
check(hook(gone, 'click')({ element }) === true && element.label.options.display === true, 'a tap shows it too');
const keptElement = { label: { options: { display: true } } };
check(hook(kept, 'leave')({ element: keptElement }) === undefined && keptElement.label.options.display === true,
      'a drawn label is not hidden when the pointer leaves its line');
check(annotations['first' + gone].hitTolerance > 0, 'a thin dashed line is easy to reach');
// Back on the tall chart, every label is drawn whole again.
fakeChart.chartArea = area(1300);
plugin.afterLayout(fakeChart);
check(ANN.every((a, i) => annotations['first' + i].label.display && annotations['first' + i].label.content === a[1]),
      'on a tall chart every label is drawn in full again');

section('stat values');
const values = page.byId('statsGrid').children.map(c => c.children[1]);
check(values.length > 0 && values.every(v => v.style['--chars'] === String(v.textContent.length)),
      'each stat value records its length: ' + values.map(v => v.style['--chars']).join(','));

done();
