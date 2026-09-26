// Offline test harness for Code.gs.
//
// Loads Code.gs into a Node VM context with in-memory stand-ins for the Apps
// Script services it uses (SpreadsheetApp, UrlFetchApp, PropertiesService,
// Utilities, ...). UrlFetchApp is a fake: no request leaves the machine and
// no API key is needed.
//
// This verifies the script's logic. It does NOT prove behaviour against the
// real Google services or the real Claude API; see the README.
//
// Usage: node test/run_tests.js      (Node 18+, no dependencies)

'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const FAKE_KEY = 'test-key-not-real-0123456789';

// ---- fake HTTP responses -------------------------------------------------

function okReply(obj, extra) {
  const body = Object.assign({
    type: 'message', role: 'assistant', stop_reason: 'end_turn',
    content: [{ type: 'thinking', thinking: '' }, { type: 'text', text: JSON.stringify(obj) }]
  }, extra || {});
  return { code: 200, body: JSON.stringify(body), headers: {} };
}
function rawText(text) {
  return { code: 200, body: JSON.stringify({ stop_reason: 'end_turn', content: [{ type: 'text', text }] }), headers: {} };
}
function httpError(code, message, headers) {
  return { code, body: JSON.stringify({ type: 'error', error: { type: 'x', message } }), headers: headers || {} };
}
const GOOD = { category: 'billing', sentiment: 'negative', summary: 'Customer was charged twice and wants a refund.' };

// ---- Apps Script stand-ins ------------------------------------------------

function makeSheet(name, grid) {
  const rows = grid.map(r => r.slice());
  let active = { row: 2, numRows: Math.max(rows.length - 1, 1) };
  const sheet = {
    name, rows, frozen: 0,
    getName: () => name,
    appendRow(r) { rows.push(r.slice()); },
    setFrozenRows(n) { this.frozen = n; },
    getLastRow: () => rows.length,
    getLastColumn: () => rows.reduce((m, r) => Math.max(m, r.length), 0),
    select(row, numRows) { active = { row, numRows }; },
    getActiveRange: () => ({ getRow: () => active.row, getNumRows: () => active.numRows }),
    getRange(row, col, numRows, numCols) {
      numRows = numRows || 1; numCols = numCols || 1;
      return {
        getValues() {
          const out = [];
          for (let r = 0; r < numRows; r++) {
            const src = rows[row - 1 + r] || [];
            const line = [];
            for (let c = 0; c < numCols; c++) line.push(src[col - 1 + c] === undefined ? '' : src[col - 1 + c]);
            out.push(line);
          }
          return out;
        },
        setValue(v) {
          while (rows.length < row) rows.push([]);
          const r = rows[row - 1];
          while (r.length < col - 1) r.push('');
          r[col - 1] = v;
          return this;
        }
      };
    }
  };
  return sheet;
}

function load(opts) {
  opts = opts || {};
  const header = ['ID', 'Message', 'Category', 'Sentiment', 'Summary'];
  const grid = opts.grid || [
    ['ID', 'Message'],
    ['M-01', 'I was charged twice this month.'],
    ['M-02', 'The export button does nothing.'],
    ['M-03', 'Love the new dashboard!']
  ];
  const data = makeSheet('Feedback', grid);
  const sheets = { Feedback: data };
  const props = {};
  if (opts.key !== null) props.ANTHROPIC_API_KEY = opts.key || FAKE_KEY;

  const calls = [];      // every request sent, in order
  const sleeps = [];
  const alerts = [];
  const logs = [];
  const toasts = [];
  const menus = [];
  const queue = (opts.responses || []).slice(); // response per request, in order
  const fallback = opts.fallback || (() => okReply(GOOD));

  const ui = {
    ButtonSet: { OK_CANCEL: 'OK_CANCEL' },
    Button: { OK: 'OK', CANCEL: 'CANCEL' },
    alert: m => alerts.push(String(m)),
    prompt: () => ({ getSelectedButton: () => 'OK', getResponseText: () => opts.promptKey || '' }),
    createMenu(title) {
      const m = { title, items: [] };
      menus.push(m);
      const chain = { addItem(label, fn) { m.items.push([label, fn]); return chain; }, addToUi() { return chain; } };
      return chain;
    }
  };

  const spreadsheet = {
    getActiveSheet: () => data,
    getSheetByName: n => sheets[n] || null,
    insertSheet: n => (sheets[n] = makeSheet(n, [])),
    toast: m => toasts.push(String(m))
  };

  const context = {
    SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet, getUi: () => ui },
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: k => (k in props ? props[k] : null),
        setProperty: (k, v) => { props[k] = v; }
      })
    },
    UrlFetchApp: {
      fetchAll(reqs) {
        return reqs.map(req => {
          calls.push(req);
          const r = queue.length ? queue.shift() : fallback(req);
          return {
            getResponseCode: () => r.code,
            getContentText: () => r.body,
            getHeaders: () => r.headers || {}
          };
        });
      }
    },
    Utilities: { sleep: ms => sleeps.push(ms) },
    Logger: { log: m => logs.push(String(m)) }
  };
  vm.createContext(context);
  const src = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8');
  vm.runInContext(src, context, { filename: 'Code.gs' });
  if (opts.config) Object.assign(context.CONFIG, opts.config);
  return { context, data, sheets, props, calls, sleeps, alerts, logs, toasts, menus, header };
}

const col = (s, name) => s.data.rows[0].indexOf(name);
const cell = (s, row, name) => s.data.rows[row - 1][col(s, name)];
const allText = s => JSON.stringify([s.sheets, s.logs, s.alerts, s.toasts]);

// ---- parsing ---------------------------------------------------------------

test('parseClassification_ accepts valid JSON and normalises it', () => {
  const s = load();
  const r = s.context.parseClassification_('{"category":" Bug ","sentiment":"NEGATIVE","summary":"Export\\nbutton   fails."}');
  assert.equal(r.error, null);
  assert.equal(r.result.category, 'bug');
  assert.equal(r.result.sentiment, 'negative');
  assert.equal(r.result.summary, 'Export button fails.', 'newlines and runs of spaces collapsed');
});

test('parseClassification_ rejects bad shapes with "needs review"', () => {
  const s = load();
  const bad = [
    'not json at all',
    '```json\n{"category":"bug"}\n```',
    '[1,2]',
    '{"category":"bug","sentiment":"negative"}',
    '{"category":"bug","sentiment":"negative","summary":"x","extra":1}',
    '{"category":"refund","sentiment":"negative","summary":"x"}',
    '{"category":"bug","sentiment":"angry","summary":"x"}',
    '{"category":"bug","sentiment":"negative","summary":"   "}',
    '{"category":7,"sentiment":"negative","summary":"x"}'
  ];
  for (const b of bad) {
    const r = s.context.parseClassification_(b);
    assert.equal(r.result.category, 'needs review', b);
    assert.equal(r.result.sentiment, 'needs review', b);
    assert.ok(r.error, 'an error reason is given for: ' + b);
  }
});

test('long summaries are trimmed to the limit', () => {
  const s = load();
  const r = s.context.parseClassification_(JSON.stringify({ category: 'other', sentiment: 'neutral', summary: 'word '.repeat(100) }));
  assert.ok(r.result.summary.length <= 200);
});

test('refusal and max_tokens stop reasons become "needs review"', () => {
  const s = load();
  for (const reason of ['refusal', 'max_tokens']) {
    const r = s.context.parseApiResponse_(JSON.stringify({ stop_reason: reason, content: [{ type: 'text', text: JSON.stringify(GOOD) }] }));
    assert.equal(r.result.category, 'needs review', reason);
  }
});

// ---- request shape ----------------------------------------------------------

test('default model is Haiku 4.5 (cheap classification)', () => {
  const s = load();
  const body = JSON.parse(s.context.buildRequest_('hello', FAKE_KEY).payload);
  assert.equal(body.model, 'claude-haiku-4-5');
});

test('request uses the configured model, strict JSON schema, and the key only in the header', () => {
  const s = load({ config: { MODEL: 'claude-opus-5' } });
  const req = s.context.buildRequest_('hello', FAKE_KEY);
  const body = JSON.parse(req.payload);
  assert.equal(body.model, 'claude-opus-5');
  assert.equal(body.output_config.format.type, 'json_schema');
  assert.equal(body.output_config.format.schema.additionalProperties, false);
  assert.deepEqual(body.output_config.format.schema.required, ['category', 'sentiment', 'summary']);
  assert.equal(body.fallbacks, 'default');
  assert.equal(req.headers['anthropic-beta'], 'server-side-fallback-2026-07-01');
  assert.equal(req.headers['x-api-key'], FAKE_KEY);
  assert.ok(!req.payload.includes(FAKE_KEY), 'key is not in the body');
  assert.equal(req.muteHttpExceptions, true);
});

test('switching to Haiku drops effort and the fallback beta', () => {
  const s = load({ config: { MODEL: 'claude-haiku-4-5' } });
  const req = s.context.buildRequest_('hello', FAKE_KEY);
  const body = JSON.parse(req.payload);
  assert.equal(body.model, 'claude-haiku-4-5');
  assert.equal(body.output_config.effort, undefined);
  assert.equal(body.fallbacks, undefined);
  assert.equal(req.headers['anthropic-beta'], undefined);
});

// ---- end-to-end with the fake HTTP layer -----------------------------------

test('classifies selected rows and adds the three output columns', () => {
  const s = load({
    responses: [
      okReply(GOOD),
      okReply({ category: 'bug', sentiment: 'negative', summary: 'Export button does nothing.' }),
      okReply({ category: 'praise', sentiment: 'positive', summary: 'Customer likes the new dashboard.' })
    ]
  });
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 3);
  assert.equal(r.needsReview, 0);
  assert.deepEqual(s.data.rows[0], ['ID', 'Message', 'Category', 'Sentiment', 'Summary']);
  assert.equal(cell(s, 2, 'Category'), 'billing');
  assert.equal(cell(s, 3, 'Category'), 'bug');
  assert.equal(cell(s, 4, 'Sentiment'), 'positive');
  assert.equal(s.calls.length, 3);
  assert.equal(s.sheets.Log, undefined, 'no Log tab when nothing went wrong');
});

test('only the selected rows are sent, and the header row is never sent', () => {
  const s = load();
  s.data.select(1, 2); // header + row 2
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 1);
  assert.equal(s.calls.length, 1);
  assert.match(JSON.parse(s.calls[0].payload).messages[0].content, /charged twice/);
});

test('skips rows that already have a Category, and empty rows', () => {
  const s = load({
    grid: [
      ['ID', 'Message', 'Category', 'Sentiment', 'Summary'],
      ['M-01', 'Already done', 'bug', 'neutral', 'Old summary'],
      ['M-02', '', '', '', ''],
      ['M-03', 'New message', '', '', ''],
      ['M-04', 'Flagged before', 'needs review', 'needs review', '']
    ]
  });
  const r = s.context.classifySelectedRows();
  assert.equal(s.calls.length, 1, 'only the new, non-empty row is sent');
  assert.equal(r.skipped, 3);
  assert.equal(cell(s, 2, 'Summary'), 'Old summary', 'existing result untouched');
  assert.equal(cell(s, 4, 'Category'), 'billing');
});

test('batches requests by BATCH_SIZE', () => {
  const grid = [['ID', 'Message']];
  for (let i = 1; i <= 7; i++) grid.push(['M-' + i, 'message ' + i]);
  const s = load({ grid, config: { BATCH_SIZE: 3 } });
  let batches = 0;
  const orig = s.context.UrlFetchApp.fetchAll;
  s.context.UrlFetchApp.fetchAll = reqs => { batches++; assert.ok(reqs.length <= 3); return orig(reqs); };
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 7);
  assert.equal(batches, 3);
});

// ---- retry ------------------------------------------------------------------

test('retries 429 and 5xx with growing backoff, then succeeds', () => {
  const s = load({
    grid: [['ID', 'Message'], ['M-01', 'hello']],
    responses: [httpError(429, 'rate limited'), httpError(529, 'overloaded'), httpError(500, 'oops'), okReply(GOOD)]
  });
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 1);
  assert.equal(s.calls.length, 4);
  assert.equal(s.sleeps.length, 3);
  assert.ok(s.sleeps[0] >= 1000 && s.sleeps[1] >= 2000 && s.sleeps[2] >= 4000, 'exponential: ' + s.sleeps);
  assert.equal(cell(s, 2, 'Category'), 'billing');
});

test('honours a retry-after header', () => {
  const s = load({
    grid: [['ID', 'Message'], ['M-01', 'hello']],
    responses: [httpError(429, 'slow down', { 'Retry-After': '7' }), okReply(GOOD)]
  });
  s.context.classifySelectedRows();
  assert.equal(s.sleeps[0], 7000);
});

test('gives up after MAX_RETRIES, marks needs review, logs the error', () => {
  const s = load({ grid: [['ID', 'Message'], ['M-01', 'hello']], fallback: () => httpError(503, 'unavailable') });
  const r = s.context.classifySelectedRows();
  assert.equal(s.calls.length, 5, '1 try + 4 retries');
  assert.equal(r.needsReview, 1);
  assert.equal(cell(s, 2, 'Category'), 'needs review');
  const log = s.sheets.Log.rows;
  assert.deepEqual([...log[0]], ['Time', 'Sheet', 'Row', 'Level', 'Message']);
  assert.equal(log[1][2], 2);
  assert.match(log[1][4], /HTTP 503: unavailable/);
});

test('400 errors are not retried', () => {
  const s = load({ grid: [['ID', 'Message'], ['M-01', 'hello']], responses: [httpError(400, 'bad request')] });
  s.context.classifySelectedRows();
  assert.equal(s.calls.length, 1);
  assert.equal(s.sleeps.length, 0);
});

test('only the failed rows in a batch are retried', () => {
  const s = load({ responses: [okReply(GOOD), httpError(429, 'x'), okReply(GOOD), okReply(GOOD)] });
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 3);
  assert.equal(s.calls.length, 4);
  assert.match(JSON.parse(s.calls[3].payload).messages[0].content, /export button/);
});

// ---- bad JSON fallback --------------------------------------------------------

test('bad JSON from the model becomes "needs review" and is logged', () => {
  const s = load({ responses: [rawText('Sure! Category: billing'), okReply(GOOD), rawText('{"category":"billing"')] });
  const r = s.context.classifySelectedRows();
  assert.equal(r.classified, 1);
  assert.equal(r.needsReview, 2);
  assert.equal(cell(s, 2, 'Category'), 'needs review');
  assert.equal(cell(s, 3, 'Category'), 'billing');
  assert.equal(s.sheets.Log.rows.length, 3, 'header + 2 errors');
});

test('overlong messages are flagged, not sent', () => {
  const s = load({ grid: [['ID', 'Message'], ['M-01', 'x'.repeat(9000)]] });
  s.context.classifySelectedRows();
  assert.equal(s.calls.length, 0);
  assert.equal(cell(s, 2, 'Category'), 'needs review');
});

// ---- key handling -----------------------------------------------------------

test('the API key never appears in the sheet, Log tab, alerts, or toasts', () => {
  const s = load({
    responses: [
      httpError(401, 'invalid x-api-key: ' + FAKE_KEY),
      rawText('garbage ' + FAKE_KEY),
      okReply(GOOD)
    ]
  });
  s.context.classifySelectedRows();
  assert.ok(s.sheets.Log.rows.length >= 3);
  assert.ok(!allText(s).includes(FAKE_KEY), 'key leaked somewhere');
  assert.match(s.sheets.Log.rows[1][4], /\[redacted\]/);
});

test('no key: alerts the user and sends nothing', () => {
  const s = load({ key: null });
  const r = s.context.classifySelectedRows();
  assert.equal(r.error, 'no_key');
  assert.equal(s.calls.length, 0);
  assert.match(s.alerts[0], /Set API key/);
});

test('setApiKey stores the key in Script Properties only', () => {
  const s = load({ key: null, promptKey: '  ' + FAKE_KEY + '  ' });
  s.context.setApiKey();
  assert.equal(s.props.ANTHROPIC_API_KEY, FAKE_KEY);
  assert.ok(!allText(s).includes(FAKE_KEY));
});

test('Code.gs has no hard-coded key', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8');
  assert.ok(!/sk-ant-[A-Za-z0-9]{10,}/.test(src));
});

test('onOpen adds the menu', () => {
  const s = load();
  s.context.onOpen();
  assert.equal(s.menus[0].title, 'AI Classifier');
  assert.deepEqual(s.menus[0].items.map(i => i[0]), ['Classify selected rows', 'Set API key']);
});
