// tests/dashboard/test_tokens_absent.js
'use strict';
const { load } = require('./harness');
const { check, section, done } = require('./check');
const { checkAbsent } = require('./tokens_absent');

const page = load({ tokens: false });
check(page.RAW.summary.tokens.per_day.length === 0 && page.RAW.commits.every(c => !c[8]), 'the variant really carries no token data');
checkAbsent(page, check, section);
done();
