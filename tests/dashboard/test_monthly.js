// tests/dashboard/test_monthly.js
// Commits and pull requests per month: the most, the fewest and the average,
// each with its month. The expected figures below are worked out by hand
// from the commits each case builds, not by the page.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const page = load();
const { RAW, byId } = page;
const activity = commits => page.run('return MONTHLY.activity(' + JSON.stringify(commits) + ')');
const c = (date, message, is_merge) => [0, '', date, message, '', is_merge ? 1 : 0];   // a commit row as the page holds it
const cards = () => byId('monthlyStats').children.map(x => ({ label: x.children[0].textContent, value: x.children[1].textContent, note: x.children[2] ? x.children[2].textContent : '' }));
const card = label => cards().find(x => x.label === label);

section('pull request numbers');
const pr = (message, is_merge) => page.run('return MONTHLY.prNumber(' + JSON.stringify(c('2026-01-01', message, is_merge)) + ')');
check(pr('Merge pull request #12 from me/branch', true) === 12, 'a GitHub merge commit');
check(pr('Add the parser (#34)') === 34, 'a squash-merge subject ending (#N)');
check(pr('Add the parser (#34)  ') === 34, 'trailing spaces after (#N)');
check(pr('Revert "Add the parser (#34)" (#40)') === 40, 'a revert names its own PR, not the reverted one');
check(pr('Revert "Add the parser (#34)"') === null, 'a revert without a PR of its own has none');
check(pr('Fix (#34) in the middle') === null, '(#N) only counts at the end of the subject');
check(pr('Fix #34') === null, 'an issue reference is not a PR');
check(pr("Merge branch 'feature' into main", true) === null, 'a plain branch merge is not a PR');

section('a history with gaps and partial ends');
// Jan 15 .. May 2: January and May are partial, February to April full.
// Commits: Jan 2, Feb 3, Mar 0, Apr 1, May 1.  PRs: Jan 1 (#1), Feb 1 (#2), Mar 0, Apr 1 (#3), May 0.
let a = activity([
  c('2026-01-15', 'a'), c('2026-01-20', 'Merge pull request #1 from me/a', true),
  c('2026-02-03', 'b (#2)'), c('2026-02-04', 'c'), c('2026-02-05', 'd'),
  c('2026-04-10', 'e (#3)'), c('2026-05-02', 'f'),
]);
check(a.months === 3 && a.full === true, 'three full months counted: ' + a.months);
check(a.commits.most.count === 3 && a.commits.most.month === '2026-02', 'most commits: February, 3');
check(a.commits.fewest.count === 0 && a.commits.fewest.month === '2026-03', 'fewest commits: the empty March, 0');
check(Math.abs(a.commits.average - 4 / 3) < 1e-9, 'average commits over the full months: 4/3, got ' + a.commits.average);
check(a.prs.most.count === 1 && a.prs.most.month === '2026-01', 'most PRs: a three-way tie goes to the earliest month, January');
check(a.prs.fewest.count === 0 && a.prs.fewest.month === '2026-03', 'fewest PRs: March');
check(Math.abs(a.prs.average - 2 / 3) < 1e-9, 'average PRs over the full months: 2/3');
check(a.prs.total === 3, 'three PRs in all');

section('the busiest month may be a partial one');
// Mar 1 .. Apr 20: March is full, April partial and busier.
a = activity([c('2026-03-01', 'a'), c('2026-04-01', 'b'), c('2026-04-02', 'c'), c('2026-04-20', 'd')]);
check(a.commits.most.month === '2026-04' && a.commits.most.count === 3, 'most commits in the partial April');
check(a.months === 1 && a.commits.fewest.month === '2026-03' && a.commits.average === 1, 'fewest and average over March alone');
check(a.prs === null, 'no PRs: no PR figures');

section('no full month');
// Mar 10 .. Apr 5: both months partial, so every month counts.
a = activity([c('2026-03-10', 'a'), c('2026-03-11', 'b'), c('2026-04-05', 'c')]);
check(a.full === false && a.months === 2, 'both partial months counted, marked as not full');
check(a.commits.fewest.month === '2026-04' && a.commits.fewest.count === 1 && a.commits.average === 1.5, 'fewest April 1, average 1.5');

section('dates out of history order');
// A rebased or cherry-picked commit keeps its author date, so the earliest
// date need not be the first row. Jan 5 .. Mar 3: only February is full.
a = activity([c('2026-02-10', 'a'), c('2026-01-05', 'b'), c('2026-03-03', 'c')]);
check(a.months === 1 && a.commits.fewest.month === '2026-02', 'the span runs from the earliest date to the latest');
check(a.commits.most.month === '2026-01' && a.commits.most.count === 1, 'the earliest-dated commit is counted in its month');

section('dates the page cannot place');
// An empty date (a commit git gave none) is left out, and so is a
// five-digit year (git stores one when asked): the month walk would never
// reach one that sorts after every real date.
a = activity([c('2026-03-01', 'a'), c('', 'b'), c('29982-11-0', 'far'), c('2026-03-31', 'c')]);
check(a.months === 1 && a.commits.most.count === 2, 'only the two dated commits, in March');
check(activity([c('', 'a')]) === null, 'no dated commit: no figures');
// Git never writes a month 13, but the walk must still stop past it.
check(activity([c('2026-01-05', 'a'), c('2026-13-01', 'b')]).commits.most.month === '2026-01', 'a month the walk cannot name still ends it');

section('ties for the fewest');
// Jan 1 .. Apr 30, all full: Jan 1, Feb 0, Mar 0, Apr 1.
a = activity([c('2026-01-01', 'a'), c('2026-04-30', 'b')]);
check(a.commits.fewest.month === '2026-02' && a.commits.most.month === '2026-01', 'ties go to the earlier month, for the fewest and the most');

section('month ends');
a = activity([c('2028-02-01', 'a'), c('2028-02-29', 'b')]);
check(a.full === true && a.months === 1, '1 to 29 February in a leap year is a full month');
a = activity([c('2026-02-01', 'a'), c('2026-02-28', 'b')]);
check(a.full === true && a.months === 1, '1 to 28 February in a common year is a full month');
a = activity([c('2025-12-01', 'a'), c('2026-01-31', 'b (#7)'), c('2026-01-31', 'Merge pull request #7 from me/b', true)]);
check(a.months === 2 && a.commits.average === 1.5, 'December to January across a year end: two full months');
check(a.prs.total === 1 && a.prs.most.count === 1, 'a PR named twice is counted once');

section('the cards');
const S = page.run('return MONTHLY.activity(ROWS)');
const month = m => new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(+m.slice(0, 4), +m.slice(5, 7) - 1, 1));
const one = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const int = new Intl.NumberFormat('en-US');
check(card('Most Commits') && card('Most Commits').value === int.format(S.commits.most.count) && card('Most Commits').note === month(S.commits.most.month),
      'Most Commits shows the count and the month: ' + JSON.stringify(card('Most Commits')));
check(card('Fewest Commits') && card('Fewest Commits').value === int.format(S.commits.fewest.count) && card('Fewest Commits').note === month(S.commits.fewest.month),
      'Fewest Commits shows its count and month');
check(card('Commits per Month') && card('Commits per Month').value === one.format(S.commits.average) &&
      card('Commits per Month').note === 'average over ' + int.format(S.months) + (S.full ? ' full' : ' partial') + ' month' + (S.months === 1 ? '' : 's'),
      'the average with its months: ' + JSON.stringify(card('Commits per Month')));
check(!!card('Most PRs') === (S.prs !== null), 'PR cards exactly when the history has PRs');
if (RAW.commits.some(x => x[5] && /^Merge pull request #\d/.test(x[3])))
  check(S.prs !== null && card('PRs per Month').value === one.format(S.prs.average), 'merge commits of pull requests give PR cards');
page.run('MONTHLY.render(' + JSON.stringify([c('2026-03-01', 'a'), c('2026-03-10', 'b')]) + ')');
check(cards().length === 3 && !card('Most PRs'), 'no PR cards for a history without PRs');
check(card('Commits per Month').note === 'average over 1 partial month', 'a single partial month says so: ' + card('Commits per Month').note);
check(byId('monthlySection').hidden === false, 'the section shows with figures');
// One PR over the 24 full months of 2024 and 2025: 1/24 would round to 0.
page.run('MONTHLY.render(' + JSON.stringify([c('2024-01-01', 'a (#1)'), c('2025-12-31', 'b')]) + ')');
check(card('PRs per Month').value === '0.042', 'a small average keeps two significant digits: ' + card('PRs per Month').value);
check(card('Commits per Month').value === '0.1', 'an average of 2/24 keeps one decimal: ' + card('Commits per Month').value);
page.run('MONTHLY.render(' + JSON.stringify([c('', 'a')]) + ')');
check(byId('monthlySection').hidden === true && cards().length === 0, 'no dated commit: the section is hidden and empty');

done();
