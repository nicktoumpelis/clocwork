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

// CLOCWORK_DASH_WORKSPACE points the suite at an already rendered workspace
// (a real one, say) instead of the synthetic fixture. It stands in for the
// default variant only: a test that asks for another variant always gets the
// synthetic one, because a real workspace is whatever it is.
const WORKSPACES = {};   // variant -> rendered directory
function workspace(variant) {
  variant = variant || 'default';
  if (variant === 'default' && process.env.CLOCWORK_DASH_WORKSPACE) return process.env.CLOCWORK_DASH_WORKSPACE;
  if (WORKSPACES[variant]) return WORKSPACES[variant];
  const root = path.resolve(__dirname, '..', '..');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'clocwork-dash-'));
  const args = [path.join(__dirname, 'fixture.py'), dir];
  if (variant === 'no-tokens') args.push('--no-tokens');
  if (variant === 'sources') args.push('--sources');
  if (variant === 'crowded') args.push('--crowded');
  execFileSync('python3', args, { stdio: 'inherit' });
  execFileSync(path.join(root, 'clocwork'), ['render', '-o', dir, '--no-open', '-q'], { stdio: 'inherit' });
  process.on('exit', () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { /* best effort */ } });
  WORKSPACES[variant] = dir;
  return dir;
}

function El(tag) {
  this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
  this.style = { setProperty(k, v) { this[k] = String(v); } }; this.className = ''; this.textContent = ''; this.value = '';
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
El.prototype.focus = function () { global.document.activeElement = this; };
El.prototype.getContext = function () { return {}; };
El.prototype.find = function (pred) { for (const c of this.children) { if (pred(c)) return c; const d = c.find(pred); if (d) return d; } return null; };
El.prototype.findAll = function (pred, out) { out = out || []; for (const c of this.children) { if (pred(c)) out.push(c); c.findAll(pred, out); } return out; };
Object.defineProperty(El.prototype, 'firstChild', { get() { return this.children[0] || null; } });
Object.defineProperty(El.prototype, 'nextSibling', { get() { if (!this.parentNode) return null; const s = this.parentNode.children; return s[s.indexOf(this) + 1] || null; } });
// Text-proportional width so the column autosize path is exercised deterministically.
Object.defineProperty(El.prototype, 'offsetWidth', { get() { const txt = this.textContent || (this.children[0] && this.children[0].textContent) || ''; return txt.length * 7 + 22; } });
Object.defineProperty(El.prototype, 'clientWidth', { get() { return this._clientWidth || 1200; }, set(v) { this._clientWidth = v; } });

function Chart(el, config) {
  // Chart.js draws nothing without a canvas; a page that asks it to has lost one.
  if (!el) throw new Error('Chart created without a canvas');
  this.el = el; this.config = config; this.data = config.data; this.options = config.options || {};
  this.updates = 0; Chart.instances.push(this);
}
Chart.instances = [];
Chart.defaults = { font: {} };
Chart.register = function () {};
Chart.prototype.update = function () { this.updates++; };
Chart.prototype.resetZoom = function () {};
Chart.prototype.isDatasetVisible = function (i) { return !(this.hidden || {})[i]; };
Chart.prototype.setDatasetVisibility = function (i, visible) { (this.hidden = this.hidden || {})[i] = !visible; };

function load(opts) {
  opts = opts || {};
  // opts.variant picks a synthetic workspace: 'no-tokens' (also opts.tokens === false), 'sources' or 'crowded'.
  const ws = workspace(opts.variant || (opts.tokens === false ? 'no-tokens' : 'default'));
  let html = fs.readFileSync(path.join(ws, 'index.html'), 'utf8');
  // opts.dropId deletes one element id from the page, to prove the page
  // cannot run without it (test_ids.js).
  if (opts.dropId) html = html.split(' id="' + opts.dropId + '"').join('');
  const scripts = []; const spans = []; const re = /<script\b[^>]*>([\s\S]*?)<\/script\b[^>]*>/gi; let m;
  while ((m = re.exec(html))) { scripts.push(m[1]); spans.push([m.index, re.lastIndex]); }
  let src = scripts.join('\n');
  // The blob may carry the region locale of the machine that generated it,
  // which the page prefers over navigator. Tests choose: opts.region sets it,
  // otherwise it is removed so the navigator path is what runs.
  const RAW = JSON.parse(src.match(/^var RAW = (.*);$/m)[1]);
  if (opts.region !== undefined) RAW.locale = opts.region; else delete RAW.locale;
  // opts.renderedBy stands in for the build that rendered the page (null
  // for a page that recorded none), so the footer is checked whatever the
  // machine running the suite can say about its own build.
  if (opts.renderedBy === null) delete RAW.rendered_by;
  else if (opts.renderedBy !== undefined) RAW.rendered_by = opts.renderedBy;
  // opts.raw edits the data blob in place before the page runs, to build a
  // workspace the fixture has no variant for (test_source_colours.js).
  if (opts.raw) opts.raw(RAW);
  src = src.replace(/^var RAW = .*;$/m, () => 'var RAW = ' + JSON.stringify(RAW) + ';');

  // Only ids the page's markup declares exist, as in a browser: any other
  // lookup gets null, so a script that needs a missing element throws.
  const declared = new Set();
  const idRe = /\sid="([^"]+)"/g;
  const inScript = at => spans.some(([from, to]) => at >= from && at < to);
  while ((m = idRe.exec(html))) if (!inScript(m.index)) declared.add(m[1]);
  const ids = {};
  const byId = id => ids[id] || (declared.has(id) ? (ids[id] = new El('div')) : null);
  const th = (cls, sort, text) => { const e = new El('th'); if (cls) e.className = cls; if (sort) e.setAttribute('data-sort', sort); e.textContent = text || ''; return e; };
  const headers = [th('expander-col'), th('sortable', 'date', 'Date'), th('', '', 'SHA'), th('sortable', 'message', 'Commit'), th('sortable', 'agent', 'Agent'), th('sortable', 'churn', '+/-'), th('sortable', 'net', 'Net'), th('sortable', 'cumulative', 'Cumulative'), th('sortable', 'tokens', 'Tokens')];
  const tabs = ['all', 'gains', 'drops'].map(k => { const b = new El('button'); b.setAttribute('data-tab', k); if (k === 'all') b.className = 'tab active'; else b.className = 'tab'; return b; });
  const cols = headers.map(() => new El('col'));
  const head = new El('head');
  // The page appends per-language <th>/<col> elements to these at load, so
  // expose the live children arrays rather than the static lists above.
  const headRow = new El('tr'); headers.forEach(x => headRow.appendChild(x));
  const colgroup = new El('colgroup'); cols.forEach(x => colgroup.appendChild(x));

  if (declared.has('allCommitsHeadRow')) ids['allCommitsHeadRow'] = headRow;
  if (declared.has('allCommitsColgroup')) ids['allCommitsColgroup'] = colgroup;

  global.window = global;
  // The theme script reads the stored choice and the system preference.
  // opts.prefersDark sets the system (light by default); opts.storage the
  // stored items, or 'refuse' for storage that throws, as a private window's
  // may. page.media.set(dark) changes the system preference as the OS would.
  // opts.media: 'none' for a browser without matchMedia, 'legacy' for one
  // whose media queries offer only addListener (Safari before 14).
  const root = new El('html');
  const store = opts.storage === 'refuse' ? null : Object.assign({}, opts.storage || {});
  global.localStorage = {
    getItem(k) { if (!store) throw new Error('storage refused'); return k in store ? store[k] : null; },
    setItem(k, v) { if (!store) throw new Error('storage refused'); store[k] = String(v); },
  };
  const media = { matches: !!opts.prefersDark, listeners: [],
                  set(dark) { this.matches = dark; this.listeners.forEach(f => f({ matches: dark })); } };
  if (opts.media === 'legacy') media.addListener = f => media.listeners.push(f);
  else media.addEventListener = (t, f) => { if (t === 'change') media.listeners.push(f); };
  if (opts.media === 'none') delete global.matchMedia;
  else global.matchMedia = q => { if (q !== '(prefers-color-scheme: dark)') throw new Error('unexpected media query ' + q); return media; };
  global.document = {
    documentElement: root,
    getElementById: byId,
    createElement: t => new El(t),
    // The selectors the page uses, each answered only while the markup
    // declares the element it hangs from.
    querySelectorAll: sel => {
      const table = declared.has('allCommitsTable');
      if (sel === '.all-commits th.sortable') return table ? headRow.children.filter(h => h.className.indexOf('sortable') >= 0) : [];
      if (sel === '#commitTabs .tab') return declared.has('commitTabs') ? tabs : [];
      if (sel === '#allCommitsTable col') return table ? colgroup.children : [];
      if (sel === '#allCommitsTable thead th') return table ? headRow.children : [];
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
    RAW, byId, declared, headers: headRow.children, tabs, cols: colgroup.children, head, charts: Chart.instances, location: global.location,
    root, media, store,
    cells: row => row.children.slice(1).map(td => td.children.length ? td.children[0].textContent : td.textContent),
    bodiesFile: path.join(ws, 'commit_bodies.js'),
    run: js => new Function(js)(),
  };
}

module.exports = { load, El };
