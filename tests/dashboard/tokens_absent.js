// tests/dashboard/tokens_absent.js
// What the page must look like for a workspace with no token data: nothing
// about tokens at all, rather than an empty section and a column of blanks.
// Shared by test_tokens.js (when the workspace it was given turns out to have
// none, as a real third-party one does) and test_tokens_absent.js (always).
'use strict';

function checkAbsent(page, check, section) {
  const { RAW, byId, headers, cols, charts } = page;
  const LANGS = RAW.languages;

  section('no token data: section');
  check(byId('tokenSection').hidden === true, 'token section is hidden');
  check(byId('tokenStats').children.length === 0, 'no token cards');
  check(charts.length === 5, 'no token chart: five charts, not six (' + charts.length + ')');

  section('no token data: commit table');
  check(!headers.some(h => h.getAttribute('data-sort') === 'tokens'), 'no Tokens header');
  check(headers.length === 8 + LANGS.length && cols.length === headers.length,
        'eight fixed columns then one per language, with a col each (' + headers.length + ' headers, ' + cols.length + ' cols)');
  check(headers.slice(8).map(h => h.textContent).join('|') === LANGS.join('|'), 'language headers follow Cumulative directly');
  const rows = byId('allCommitsBody').children.filter(r => r.className.indexOf('detail-row') < 0);
  check(rows.length > 0 && rows.every(r => r.children.length === headers.length), 'every row has exactly one cell per header');
  const top = rows[0];
  top.fire('click');
  check(!!top.nextSibling && top.nextSibling.className === 'detail-row' && top.nextSibling.children[0].colSpan === headers.length,
        'detail row spans every remaining column');
  top.fire('click');
}

module.exports = { checkAbsent };
