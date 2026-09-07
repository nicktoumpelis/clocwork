// tests/dashboard/test_numbering.js
// Loads the page under a locale whose default numbering system is not Latin
// (Egyptian Arabic uses Arabic-Indic digits) so that a number concatenated
// raw into prose, invisible in a German run where 25 is still "25", fails.
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');

const LOCALE = 'ar-EG';
const page = load({ locale: LOCALE });
const { RAW, byId } = page;
const T = RAW.summary.tokens;
const int = new Intl.NumberFormat(LOCALE);
const note = byId('tokenNote').textContent;
const measured = byId('tokenStats').children.find(x => x.children[0].textContent === 'Measured').children[2].textContent;

section('digits follow the numbering system');
check(int.format(25) !== '25', 'sanity: ar-EG digits differ from ASCII');
check(note.indexOf(' across ' + int.format(T.measured_days) + ' days') > 0, 'token note day count: ' + note.slice(0, 80));
check(note.indexOf('about ' + int.format(30) + ' days') > 0, 'token note retention window');
check(measured.indexOf(int.format(T.measured_days) + ' days from ') === 0, 'measured card day count: ' + measured);
check(byId('allCommitsCount').textContent.indexOf(int.format(500)) > 0, 'table headline row cap');

done();
