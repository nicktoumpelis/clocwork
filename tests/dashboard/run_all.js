// tests/dashboard/run_all.js
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
const files = ['test_selection.js', 'test_charts.js', 'test_table.js', 'test_tokens.js', 'test_tokens_absent.js', 'test_tokens_sources.js','test_locale.js', 'test_numbering.js', 'test_region.js'];
// West of Greenwich, so a 'YYYY-MM-DD' parsed as UTC midnight would render as
// the previous day and fail the date checks.
const env = Object.assign({}, process.env, { TZ: 'America/Los_Angeles' });
let failed = false;
for (const f of files) {
  console.log('=== ' + f);
  try { execFileSync(process.execPath, [path.join(__dirname, f)], { stdio: 'inherit', env }); }
  catch (e) { failed = true; }
}
process.exit(failed ? 1 : 0);
