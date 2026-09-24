// Offline test harness for Code.gs.
//
// Loads Code.gs into a Node VM context with small in-memory stand-ins for the
// Apps Script services it uses (SpreadsheetApp, MailApp, LockService, ...),
// then runs the script's own test functions and checks the results.
//
// This verifies the script's logic. It does NOT prove behaviour against the
// real Google services; see the README for what was and wasn't tested.
//
// Usage: node test/run_tests.js      (Node 18+, no dependencies)

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeServices() {
  const sheets = {};
  const sent = [];
  const logs = [];
  const triggers = [];
  const props = {};

  function makeSheet(name) {
    const rows = [];
    return {
      name, rows, frozen: 0,
      appendRow(r) { rows.push(r.slice()); },
      setFrozenRows(n) { this.frozen = n; },
      getLastRow() { return rows.length; },
      getRange(row, col, numRows, numCols) {
        return {
          setFontWeight() { return this; },
          getValues() {
            return rows.slice(row - 1, row - 1 + (numRows || 1))
              .map(r => r.slice(col - 1, col - 1 + (numCols || 1)));
          }
        };
      }
    };
  }

  const spreadsheet = {
    getSheetByName: n => sheets[n] || null,
    insertSheet: n => (sheets[n] = makeSheet(n)),
    getUrl: () => 'https://docs.google.com/spreadsheets/d/TEST'
  };

  const triggerBuilder = (handler) => {
    const t = { handler, kind: null };
    const chain = {
      forSpreadsheet() { return chain; },
      onFormSubmit() { t.kind = 'formSubmit'; return chain; },
      timeBased() { t.kind = 'time'; return chain; },
      everyDays(n) { t.everyDays = n; return chain; },
      atHour(h) { t.hour = h; return chain; },
      inTimezone(z) { t.tz = z; return chain; },
      create() { triggers.push(t); return { getHandlerFunction: () => handler }; }
    };
    return chain;
  };

  const context = {
    SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet },
    MailApp: { sendEmail: (to, subject, body) => sent.push({ to, subject, body }) },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'owner@example.com' }) },
    Logger: { log: m => logs.push(String(m)) },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: k => (k in props ? props[k] : null),
        setProperty: (k, v) => { props[k] = v; }
      })
    },
    Utilities: {
      // Simplified: ignores the timezone argument; enough for the harness.
      formatDate: (d, _tz, _fmt) => d.toISOString().slice(0, 16).replace('T', ' ')
    },
    ScriptApp: {
      getProjectTriggers: () => triggers.map(t => ({ getHandlerFunction: () => t.handler })),
      deleteTrigger: (t) => {
        const i = triggers.findIndex(x => x.handler === t.getHandlerFunction());
        if (i >= 0) triggers.splice(i, 1);
      },
      newTrigger: triggerBuilder
    }
  };
  return { context, sheets, sent, logs, triggers, props };
}

function load() {
  const svc = makeServices();
  vm.createContext(svc.context);
  const src = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8');
  vm.runInContext(src, svc.context, { filename: 'Code.gs' });
  return svc;
}

test('routes by category, stamps IDs, creates tabs with headers', () => {
  const s = load();
  const results = s.context.testHandleFormSubmit();
  assert.equal(results.map(r => r.id).join(','), 'REQ-00001,REQ-00002');
  assert.equal(results[0].tab, 'Billing');
  assert.equal(results[1].tab, 'Other', 'unknown category falls back');
  const billing = s.sheets.Billing.rows;
  assert.equal(billing[0][0], 'ID');
  assert.equal(billing.length, 2);
  assert.equal(billing[1][0], 'REQ-00001');
  assert.equal(billing[1][3], 'New');
  assert.equal(Object.prototype.toString.call(billing[1][2]), '[object Date]', 'processed timestamp stamped');
  assert.match(s.sheets.Other.rows[1][9], /Order number: A-1001/, 'extra fields kept in Details');
});

test('High priority alerts; DRY_RUN in the test function sends nothing', () => {
  const s = load();
  s.context.testHandleFormSubmit();
  assert.equal(s.sent.length, 0);
  const alert = s.logs.find(l => l.includes('[High priority] REQ-00001'));
  assert.ok(alert, 'alert was generated for the High item');
  assert.ok(!s.logs.some(l => l.includes('[High priority] REQ-00002')), 'no alert for Low');
});

test('real (non-dry-run) submit sends one email for High, none for Low', () => {
  const s = load();
  const ev = (p) => ({ namedValues: { Name: ['A'], Category: ['Technical'], Priority: [p] } });
  s.context.handleFormSubmit(ev('High'));
  s.context.handleFormSubmit(ev('low'));
  s.context.handleFormSubmit(ev(' HIGH '));
  assert.equal(s.sent.length, 2);
  assert.equal(s.sent[0].to, 'owner@example.com');
  assert.match(s.sent[0].subject, /REQ-00001 - Technical/);
});

test('missing event object fails loudly', () => {
  const s = load();
  assert.throws(() => s.context.handleFormSubmit(undefined), /needs a form-submit event/);
});

test('daily digest counts recent rows and lists High items', () => {
  const s = load();
  s.context.testHandleFormSubmit();
  // An old, closed row that should not count as new or open.
  s.sheets.Billing.appendRow(['REQ-00099', new Date('2020-01-01'), new Date('2020-01-01'),
    'Done', 'Old', 'old@example.com', 'Billing', 'High', 'Old issue', '']);
  const r = s.context.testDailyDigest();
  assert.equal(r.total, 2);
  assert.equal(r.high, 1);
  const body = s.logs.find(l => l.startsWith('DRY RUN') && l.includes('Daily digest'));
  assert.match(body, /Billing: 1 new, 1 open/);
  assert.match(body, /Other: 1 new, 1 open/);
});

test('installTriggers creates exactly one of each, idempotently', () => {
  const s = load();
  s.context.installTriggers();
  s.context.installTriggers();
  assert.deepEqual(s.triggers.map(t => t.kind).sort(), ['formSubmit', 'time']);
  assert.equal(s.triggers.find(t => t.kind === 'time').hour, 7);
});
