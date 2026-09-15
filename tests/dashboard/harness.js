// tests/dashboard/harness.js
// Renders the synthetic workspace from fixture.py through `clocwork render`,
// then runs the page script inside a minimal fake DOM so table and chart
// logic can be exercised from node. Only the DOM surface the page uses is
// implemented; extend it when the page starts using something new.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

let WORKSPACE = null;
function workspace() {
  if (WORKSPACE) return WORKSPACE;
  const root = path.resolve(__dirname, '..', '..');
  WORKSPACE = fs.mkdtempSync(path.join(os.tmpdir(), 'clocwork-dash-'));
  execFileSync('python3', [path.join(__dirname, 'fixture.py'), WORKSPACE], { stdio: 'inherit' });
  execFileSync(path.join(root, 'clocwork'), ['render', '-o', WORKSPACE, '--no-open', '-q'], { stdio: 'inherit' });
  return WORKSPACE;
}

function El(tag) {
  this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
  this.style = {}; this.className = ''; this.textContent = ''; this.value = '';
  this.hidden = false; this.parentNode = null;
  const self = this;
  this.classList = {
    add(c) { if (!self.classList.contains(c)) self.className = (self.className + ' ' + c).trim(); },
    remove(c) { self.className = self.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
    contains(c) { return self.className.split(/\s+/).indexOf(c) >= 0; },
  };
}
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.removeChild = function (c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; };
El.prototype.insertBefore = function (n, ref) { const i = this.children.indexOf(ref); if (i < 0) this.children.push(n); else this.children.splice(i, 0, n); n.parentNode = this; return n; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.removeEventListener = function (t, f) { const l = this.listeners[t] || []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); };
El.prototype.fire = function (t, evt) { (this.listeners[t] || []).slice().forEach(f => f(evt || { target: {} })); };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.getContext = function () { return {}; };
El.prototype.find = function (pred) { for (const c of this.children) { if (pred(c)) return c; const d = c.find(pred); if (d) return d; } return null; };
El.prototype.findAll = function (pred, out) { out = out || []; for (const c of this.children) { if (pred(c)) out.push(c); c.findAll(pred, out); } return out; };
Object.defineProperty(El.prototype, 'firstChild', { get() { return this.children[0] || null; } });
Object.defineProperty(El.prototype, 'nextSibling', { get() { if (!this.parentNode) return null; const s = this.parentNode.children; return s[s.indexOf(this) + 1] || null; } });
// Text-proportional width so the column autosize path is exercised deterministically.
Object.defineProperty(El.prototype, 'offsetWidth', { get() { const txt = this.textContent || (this.children[0] && this.children[0].textContent) || ''; return txt.length * 7 + 22; } });
Object.defineProperty(El.prototype, 'clientWidth', { get() { return this._clientWidth || 1200; }, set(v) { this._clientWidth = v; } });

function Chart(el, config) {
  this.el = el; this.config = config; this.data = config.data; this.options = config.options || {};
  this.updates = 0; Chart.instances.push(this);
}
Chart.instances = [];
Chart.defaults = { font: {} };
Chart.register = function () {};
Chart.prototype.update = function () { this.updates++; };
Chart.prototype.resetZoom = function () {};

function load(opts) {
  opts = opts || {};
  const html = fs.readFileSync(path.join(workspace(), 'index.html'), 'utf8');
  const scripts = []; const re = /<script>([\s\S]*?)<\/script>/g; let m;
  while ((m = re.exec(html))) scripts.push(m[1]);
  let src = scripts.join('\n');
  // The blob may carry the region locale of the machine that generated it,
  // which the page prefers over navigator. Tests choose: opts.region sets it,
  // otherwise it is removed so the navigator path is what runs.
  const RAW = JSON.parse(src.match(/^var RAW = (.*);$/m)[1]);
  if (opts.region !== undefined) RAW.locale = opts.region; else delete RAW.locale;
  src = src.replace(/^var RAW = .*;$/m, () => 'var RAW = ' + JSON.stringify(RAW) + ';');

  const ids = {};
  const byId = id => ids[id] || (ids[id] = new El('div'));
  const th = (cls, sort, text) => { const e = new El('th'); if (cls) e.className = cls; if (sort) e.setAttribute('data-sort', sort); e.textContent = text || ''; return e; };
  const headers = [th('expander-col'), th('sortable', 'date', 'Date'), th('', '', 'SHA'), th('sortable', 'message', 'Commit'), th('sortable', 'agent', 'Agent'), th('sortable', 'churn', '+/-'), th('sortable', 'net', 'Net'), th('sortable', 'cumulative', 'Cumulative'), th('sortable', 'tokens', 'Tokens')];
  const tabs = ['all', 'gains', 'drops'].map(k => { const b = new El('button'); b.setAttribute('data-tab', k); if (k === 'all') b.className = 'tab active'; else b.className = 'tab'; return b; });
  const cols = headers.map(() => new El('col'));
  const head = new El('head');
  // The page appends per-language <th>/<col> elements to these at load, so
  // expose the live children arrays rather than the static lists above.
  const headRow = new El('tr'); headers.forEach(x => headRow.appendChild(x));
  const colgroup = new El('colgroup'); cols.forEach(x => colgroup.appendChild(x));

  ids['allCommitsHeadRow'] = headRow;
  ids['allCommitsColgroup'] = colgroup;

  global.window = global;
  global.document = {
    getElementById: byId,
    createElement: t => new El(t),
    querySelectorAll: sel => {
      if (sel === '.all-commits th.sortable') return headRow.children.filter(h => h.className.indexOf('sortable') >= 0);
      if (sel === '#commitTabs .tab') return tabs;
      if (sel === '#allCommitsTable col') return colgroup.children;
      if (sel === '#allCommitsTable thead th') return headRow.children;
      return [];
    },
    head,
    addEventListener() {}, removeEventListener() {},
  };
  // The page reads the viewer's locale from navigator; default to en-US so
  // assertions do not depend on the machine running the tests. Node 21+
  // exposes a getter-only navigator, hence defineProperty over assignment.
  const locale = opts.locale || 'en-US';
  Object.defineProperty(global, 'navigator', { value: { language: locale, languages: [locale] }, configurable: true, writable: true });
  global.location = { hash: opts.hash || '' };
  global.history = { replaceState(_s, _t, h) { global.location.hash = h; } };
  Chart.instances = [];
  global.Chart = Chart;

  // runInThisContext (not new Function) so the page's top-level `var`s
  // (RAW, SEL, ROWS, ...) become globals that page.run() can reach.
  require('vm').runInThisContext(src);

  return {
    RAW, byId, headers: headRow.children, tabs, cols: colgroup.children, head, charts: Chart.instances, location: global.location,
    cells: row => row.children.slice(1).map(td => td.children.length ? td.children[0].textContent : td.textContent),
    bodiesFile: path.join(workspace(), 'commit_bodies.js'),
    run: js => new Function(js)(),
  };
}

module.exports = { load, El };
