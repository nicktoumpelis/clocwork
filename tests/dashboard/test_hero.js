// tests/dashboard/test_hero.js
// The hero row: how much of the repository is AI, as the share of its code
// at HEAD from AI-assisted commits (or of the lines added, without a blame
// pass), of its commits and of its pull requests, and its tokens. The
// expected figures are worked out by hand from the rows each case builds.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId } = page;
const S = RAW.summary;
const pct = n => new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 0 }).format(n);
const int = n => new Intl.NumberFormat('en-US').format(n);
const cards = p => p.byId('heroGrid').children.map(x => ({ label: x.children[0].textContent, value: x.children[1].textContent,
                                                           note: x.children[2].textContent, spark: x.children[3].innerHTML, title: x.title }));
const card = (p, label) => cards(p).find(x => x.label === label);
// A commit row as the page holds it: [index, hash, date, subject, agent, isMerge, lines, testLines, tokens, kind, pr].
const c = (date, agent, codeAdded, opts) => {
  opts = opts || {};
  return [0, '', date, opts.subject || 'x', agent || '', opts.merge ? 1 : 0, codeAdded ? [[0, [codeAdded, 0, 0, 0, 0, 0]]] : [], [],
          opts.tokens || 0, opts.kind || '', opts.pr || 0];
};
const compute = rows => page.run('return HERO.compute(' + JSON.stringify(rows) + ')');

section('per month');
// January: 2 human commits of 10 and 20 lines, one AI of 30; a merge for PR #1
// holding the AI commit. February: one AI commit of 5 lines squash-merged as
// PR #2, one human of 0 lines. March: a merge for PR #3 with a human member.
let a = compute([
  c('2026-01-02', '', 10), c('2026-01-03', '', 20, { pr: 1 }), c('2026-01-04', 'Claude Opus 4.6', 30, { pr: 1, tokens: 700, kind: 'm' }),
  c('2026-01-05', 'Misc', 0, { merge: true, subject: 'Merge pull request #1 from me/a', pr: 1 }),
  c('2026-02-01', 'Claude Opus 4.6', 5, { subject: 'b (#2)', pr: 2, tokens: 300, kind: 'e' }), c('2026-02-02', '', 0),
  c('2026-03-01', '', 4, { pr: 3 }), c('2026-03-02', 'Misc', 0, { merge: true, subject: 'Merge pull request #3 from me/c', pr: 3 }),
]);
check(a.keys.join(',') === '2026-01,2026-02,2026-03', 'months in order');
check(a.months[0].commits === 3 && a.months[0].aiCommits === 1, 'January: three non-merge commits, one AI');
check(a.months[0].lines === 60 && a.months[0].aiLines === 30, 'January: 60 code lines added, 30 of them AI');
check(a.months[0].prs === 1 && a.months[0].aiPrs === 1, 'January: PR #1 holds an AI commit');
check(a.months[1].prs === 1 && a.months[1].aiPrs === 1, 'February: the squash merge is its own PR, AI');
check(a.months[2].prs === 1 && a.months[2].aiPrs === 0, 'March: PR #3 is human');
check(a.months[0].tokens === 700 && a.months[1].tokens === 300, 'tokens per month');
check(a.totals.commits === 6 && a.totals.aiCommits === 2 && a.totals.lines === 69 && a.totals.aiLines === 35 && a.totals.prs === 3 && a.totals.aiPrs === 2,
      'totals: ' + JSON.stringify(a.totals));
check(a.agentCommits['Claude Opus 4.6'] === 2 && a.agentLines['Claude Opus 4.6'] === 35, 'per agent');
check(compute([]).keys.length === 0 && compute([]).totals.commits === 0, 'no rows: nothing, no error');
check(compute([c('undated', '', 3)]).totals.commits === 0, 'a row without a dated month is left out');

section('sparkline');
check(page.run('return HERO.sparkline([1])') === '' && page.run('return HERO.sparkline([])') === '', 'fewer than two points draw nothing');
const svg = page.run('return HERO.sparkline([0, 0.5, 1])');
check(/^<svg /.test(svg) && svg.indexOf('<circle cx="100.0" cy="2.0"') >= 0, 'the last point is the dot, at the top for the maximum');
check(svg.indexOf('M0.0 23.0 L50.0 12.5 L100.0 2.0') >= 0, 'points spread over the width, the minimum at the foot');
check(page.run('return HERO.sparkline([0, 0])').indexOf('M0.0 23.0 L100.0 23.0') >= 0, 'all zero stays on the foot rather than dividing by zero');

section('the cards on the fixture');
const nonMerge = RAW.commits.filter(x => !x[5]), ai = nonMerge.filter(x => x[4] && x[4] !== 'Misc');
const L = S.lines_at_head;
const aiAt = Object.keys(L.by_agent).filter(k => k !== 'Misc').reduce((n, k) => n + L.by_agent[k], 0);
check(cards(page).map(x => x.label).join('|') === 'Code from AI-assisted commits|AI-assisted commits|AI-assisted pull requests|Tokens', 'four cards in order');
check(card(page, 'Code from AI-assisted commits').value === pct(aiAt / L.total), 'code share from the blamed lines: ' + card(page, 'Code from AI-assisted commits').value);
check(card(page, 'Code from AI-assisted commits').note.indexOf(int(aiAt) + ' of ' + int(L.total) + ' lines at HEAD') === 0, 'with its counts');
const most = Object.keys(L.by_agent).sort((x, y) => L.by_agent[y] - L.by_agent[x])[0];
check(card(page, 'Code from AI-assisted commits').note.indexOf('most by ' + most) > 0, 'and the agent with most lines: ' + most);
check(card(page, 'AI-assisted commits').value === pct(ai.length / nonMerge.length), 'commit share over non-merge commits');
check(card(page, 'AI-assisted commits').note.indexOf(int(ai.length) + ' of ' + int(nonMerge.length) + ' commits, merges aside') === 0, 'with its counts');
const prs = {};
RAW.commits.forEach(x => { if (x[10]) { prs[x[10]] = prs[x[10]] || false; if (x[4] && x[4] !== 'Misc') prs[x[10]] = true; } });
const prCount = Object.keys(prs).length, aiPrs = Object.keys(prs).filter(k => prs[k]).length;
check(prCount > 0 && aiPrs < prCount, 'sanity: the fixture has pull requests, not all AI (' + aiPrs + ' of ' + prCount + ')');
check(card(page, 'AI-assisted pull requests').value === pct(aiPrs / prCount) && card(page, 'AI-assisted pull requests').note.indexOf(int(aiPrs) + ' of ' + int(prCount) + ' pull requests') === 0,
      'pull request share: ' + card(page, 'AI-assisted pull requests').value);
const T = S.tokens, measured = RAW.commits.filter(x => x[8] && x[9] === 'm').length;
check(card(page, 'Tokens').value === new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 3 }).format(T.measured_total), 'tokens measured, compact');
check(card(page, 'Tokens').note.indexOf('over ' + int(T.measured_days) + ' measured days') === 0 && card(page, 'Tokens').note.indexOf('per AI-assisted commit') > 0 && measured > 0,
      'tokens note names the days and the rate per commit: ' + card(page, 'Tokens').note);
check(cards(page).every(x => /^<svg /.test(x.spark)), 'every card has a sparkline');
check(cards(page).every(x => x.title.length > 40), 'every card explains itself on hover');
check(byId('headline').textContent === '· ' + pct(aiAt / L.total) + ' of its code from AI-assisted commits', 'the headline is the hero figure: ' + byId('headline').textContent);
check(!byId('statsGrid').children.some(x => x.children[0].textContent === 'AI-Assisted'), 'the old AI-assisted tile is gone, its figure being the hero');

section('without a blame pass');
const older = load({ raw: r => { delete r.summary.lines_at_head; } });
check(card(older, 'Lines added in AI-assisted commits') !== undefined && card(older, 'Code from AI-assisted commits') === undefined, 'the first card falls back to lines added');
const added = nonMerge.reduce((n, x) => n + x[6].reduce((m, e) => m + e[1][0], 0), 0);
const aiAdded = ai.reduce((n, x) => n + x[6].reduce((m, e) => m + e[1][0], 0), 0);
check(card(older, 'Lines added in AI-assisted commits').value === pct(aiAdded / added) && card(older, 'Lines added in AI-assisted commits').note.indexOf(int(aiAdded) + ' of ' + int(added) + ' code lines added') === 0,
      'as a share of code lines added: ' + card(older, 'Lines added in AI-assisted commits').value);
check(older.byId('headline').textContent === '· ' + pct(ai.length / nonMerge.length) + ' of its commits AI-assisted', 'and the headline is the commit share');
const nullified = load({ raw: r => { r.summary.lines_at_head = null; } });
check(card(nullified, 'Lines added in AI-assisted commits') !== undefined, 'a null from a failed blame falls back the same way');

section('without pull requests or tokens');
const noPrs = load({ raw: r => { r.commits.forEach(x => { x[10] = 0; }); } });
check(cards(noPrs).map(x => x.label).join('|') === 'Code from AI-assisted commits|AI-assisted commits|Tokens', 'no pull request card without pull requests');
const noTokens = load({ tokens: false });
check(cards(noTokens).map(x => x.label).join('|') === 'Code from AI-assisted commits|AI-assisted commits|AI-assisted pull requests', 'no tokens card without token data');

done();
