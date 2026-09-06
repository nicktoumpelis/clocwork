// tests/dashboard/check.js
'use strict';
let failures = 0, total = 0, current = '';
function section(name) { current = name; console.log('\n## ' + name); }
function check(cond, msg) { total++; if (cond) console.log('  ok   ' + msg); else { failures++; console.log('  FAIL ' + msg + (current ? '  [' + current + ']' : '')); } }
function done() { console.log('\n' + (failures ? failures + ' of ' + total + ' checks FAILED' : 'all ' + total + ' checks passed')); if (failures) process.exitCode = 1; }
module.exports = { check, section, done };
