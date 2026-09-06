// tests/dashboard/run_all.js
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
const files = ['test_selection.js', 'test_table.js'];
let failed = false;
for (const f of files) {
  console.log('=== ' + f);
  try { execFileSync(process.execPath, [path.join(__dirname, f)], { stdio: 'inherit' }); }
  catch (e) { failed = true; }
}
process.exit(failed ? 1 : 0);
