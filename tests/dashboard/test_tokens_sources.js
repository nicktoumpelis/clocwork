// tests/dashboard/test_tokens_sources.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');
const { charted, checkSources } = require('./tokens_sources');

const page = load({ variant: 'sources' });
const { RAW, byId, cells } = page;
const T = RAW.summary.tokens;
check(charted(T).map(s => s.key).join() === 'claude-code,codex,gemini', 'the variant really carries three sources');
checkSources(page, check, section);

section('a source whose tokens land on no commit');
const note = byId('tokenNote').textContent;
check(/No commit credited to Gemini CLI changed a line[^.]*land on no commit/.test(note), 'the note says Gemini CLI\u2019s tokens land on no commit');
check(note.indexOf('adds no co-author trailer') > 0, 'and why');
check(note.indexOf('Across the agents with a rate, that is ' + new Intl.NumberFormat('en-US').format(700)) > 0, 'the blended rate is stated');

section('the tokens column follows each commit\u2019s own kind');
const dayKind = {};
T.per_day.forEach(([d, , k]) => { dayKind[d] = k; });
const byHash = {};
RAW.commits.forEach(c => { byHash[c[1]] = c; });
const shown = byId('allCommitsBody').children.filter(r => r.className.indexOf('detail-row') < 0);
const mixed = shown.filter(r => { const c = byHash[cells(r)[1]]; return c[8] && c[9] === 'm' && dayKind[c[2]] === 'e'; });
check(mixed.length > 0, 'sanity: some shown commits have a measured share of a day whose total is estimated (' + mixed.length + ')');
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 3 });
check(mixed.every(r => cells(r)[7] === compact.format(byHash[cells(r)[1]][8])), 'their figures are shown as measured, with no approximation sign');
check(mixed.every(r => / a measured day /.test(r.children[8].title)), 'and their tooltips say measured');

done();
