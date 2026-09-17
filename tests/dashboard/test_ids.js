// tests/dashboard/test_ids.js
// The harness gives the page only the elements its markup declares, so a
// check on an element proves the element exists. This file proves that the
// harness does so: every id the scripts look up is declared, and removing any
// one of them stops the page from loading.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
check(page.byId('noSuchElement') === null, 'an undeclared id is null, as in a browser');

section('every id the scripts look up');
const fs = require('fs');
const path = require('path');
const template = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'clocwork', 'template.html'), 'utf8');
const looked = new Set();
const re = /getElementById\('([^']+)'\)/g;
let m;
while ((m = re.exec(template))) looked.add(m[1]);
// set(id, …) in the header takes its ids as arguments.
const setRe = /\bset\('([^']+)'/g;
while ((m = setRe.exec(template))) looked.add(m[1]);
check(looked.size >= 30, 'found the lookups: ' + looked.size);
const undeclared = [...looked].filter(id => !page.declared.has(id));
check(undeclared.length === 0, 'all declared in the markup' + (undeclared.length ? ': missing ' + undeclared.join(', ') : ''));

section('the page needs each of them');
// The token section is looked up only when there are no tokens, so an id
// counts as needed when either workspace fails to load without it. The zoom
// button is reached only from the zoom callbacks, so those run too.
function fails(opts) {
  try {
    const p = load(opts);
    p.run('resetMainZoom()');
    p.charts[0].options.plugins.zoom.zoom.onZoomComplete();
    return false;
  } catch (e) { return true; }
}
// Anything thrown counts as a failure, so the untouched page must not throw.
check(!fails({}) && !fails({ tokens: false }), 'the untouched page loads and zooms');
// Elements the page checks for and works without, each with what it loses.
const OPTIONAL = {
  commitList: 'the commit table keeps its default column widths',
};
const unneeded = [...looked].filter(id => !fails({ dropId: id }) && !fails({ dropId: id, tokens: false }));
check(JSON.stringify(unneeded.sort()) === JSON.stringify(Object.keys(OPTIONAL).sort()),
      'removing any one fails the load, except the optional ' + Object.keys(OPTIONAL).join(', ') + ': ' + JSON.stringify(unneeded));

done();
