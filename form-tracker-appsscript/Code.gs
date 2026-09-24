/**
 * Form Response Tracker for Google Sheets (Apps Script)
 *
 * - handleFormSubmit: installable "On form submit" trigger. Stamps each response
 *   with a unique ID and a processed timestamp, copies it to a status tab chosen
 *   by its category, and emails an alert when Priority is High.
 * - sendDailyDigest: time-driven trigger. Emails a summary of the last 24 hours.
 * - installTriggers: run once to create both triggers.
 * - testHandleFormSubmit / testDailyDigest: run from the editor to try it
 *   without submitting the form (uses a simulated event object).
 *
 * Bind this script to the spreadsheet that receives the form's responses.
 */

var CONFIG = {
  // Form question titles (must match the form exactly).
  CATEGORY_FIELD: 'Category',
  PRIORITY_FIELD: 'Priority',
  // Category -> destination tab. Anything unlisted goes to FALLBACK_TAB.
  ROUTES: {
    'Billing': 'Billing',
    'Technical': 'Technical',
    'Account': 'Account',
    'Feedback': 'Feedback'
  },
  FALLBACK_TAB: 'Other',
  // Column order for every status tab. Form fields not listed here are
  // appended into the Details column so nothing is lost.
  FIELDS: ['Name', 'Email', 'Category', 'Priority', 'Description'],
  STATUS_DEFAULT: 'New',
  ID_PREFIX: 'REQ-',
  TIMEZONE: 'America/Los_Angeles',
  // Leave blank to send alerts and digests to the script owner.
  ALERT_EMAIL: '',
  DIGEST_HOUR: 7,
  // When true, emails are logged instead of sent (handy while testing).
  DRY_RUN: false
};

var HEADERS = ['ID', 'Received', 'Processed', 'Status']
  .concat(CONFIG.FIELDS)
  .concat(['Details']);

/** Installable trigger target: Extensions > Apps Script > Triggers > On form submit. */
function handleFormSubmit(e) {
  if (!e || !e.namedValues) {
    throw new Error('handleFormSubmit needs a form-submit event. Use testHandleFormSubmit() to try it manually.');
  }
  var answers = flattenNamedValues_(e.namedValues);
  var category = (answers[CONFIG.CATEGORY_FIELD] || '').trim();
  var tabName = CONFIG.ROUTES[category] || CONFIG.FALLBACK_TAB;
  var priority = (answers[CONFIG.PRIORITY_FIELD] || '').trim();

  var lock = LockService.getScriptLock();
  lock.waitLock(30000); // serialise ID generation across simultaneous submits
  var id, row;
  try {
    id = nextId_();
    var now = new Date();
    var received = answers['Timestamp'] ? new Date(answers['Timestamp']) : now;
    if (isNaN(received.getTime())) received = now;
    row = buildRow_(id, received, now, answers);
    var sheet = getOrCreateTab_(tabName);
    sheet.appendRow(row);
  } finally {
    lock.releaseLock();
  }

  if (priority.toLowerCase() === 'high') {
    sendAlert_(id, tabName, answers);
  }
  return { id: id, tab: tabName, priority: priority };
}

/** Time-driven trigger target: emails a summary of rows received in the last 24h. */
function sendDailyDigest() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var since = new Date(Date.now() - 24 * 60 * 60 * 1000);
  var tabs = uniqueTabs_();
  var total = 0;
  var high = [];
  var lines = [];

  tabs.forEach(function (name) {
    var sheet = ss.getSheetByName(name);
    if (!sheet || sheet.getLastRow() < 2) return;
    var data = sheet.getRange(2, 1, sheet.getLastRow() - 1, HEADERS.length).getValues();
    var col = indexOf_(HEADERS);
    var recent = data.filter(function (r) { return new Date(r[col.Received]) >= since; });
    var open = data.filter(function (r) { return r[col.Status] !== 'Done'; });
    if (recent.length === 0 && open.length === 0) return;
    total += recent.length;
    lines.push(name + ': ' + recent.length + ' new, ' + open.length + ' open');
    recent.forEach(function (r) {
      if (String(r[col.Priority]).toLowerCase() === 'high') {
        high.push(r[col.ID] + ' (' + name + ') ' + r[col.Name] + ': ' + truncate_(r[col.Description], 80));
      }
    });
  });

  var subject = 'Daily digest: ' + total + ' new request' + (total === 1 ? '' : 's');
  var body = [
    'Requests received since ' + formatDate_(since) + '.',
    '',
    lines.length ? lines.join('\n') : 'No new or open requests.',
    '',
    'High priority in the last 24h:',
    high.length ? high.map(function (h) { return '- ' + h; }).join('\n') : '- none',
    '',
    'Sheet: ' + ss.getUrl()
  ].join('\n');
  send_(subject, body);
  return { total: total, high: high.length, subject: subject };
}

/** Run once from the editor. Removes this project's old triggers, then creates both. */
function installTriggers() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var fn = t.getHandlerFunction();
    if (fn === 'handleFormSubmit' || fn === 'sendDailyDigest') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('handleFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
  ScriptApp.newTrigger('sendDailyDigest').timeBased().everyDays(1)
    .atHour(CONFIG.DIGEST_HOUR).inTimezone(CONFIG.TIMEZONE).create();
}

// ------------------------------------------------------------------ tests

/** Builds a fake form-submit event and runs the handler. Safe: DRY_RUN is forced on. */
function testHandleFormSubmit() {
  var previous = CONFIG.DRY_RUN;
  CONFIG.DRY_RUN = true;
  try {
    var results = [
      makeTestEvent_({ Name: 'Test User', Email: 'test.user@example.com', Category: 'Billing',
        Priority: 'High', Description: 'Charged twice for the same order.' }),
      makeTestEvent_({ Name: 'Sample Person', Email: 'sample@example.com', Category: 'Shipping',
        Priority: 'Low', Description: 'Where is my parcel?', 'Order number': 'A-1001' })
    ].map(handleFormSubmit);
    Logger.log(JSON.stringify(results));
    return results;
  } finally {
    CONFIG.DRY_RUN = previous;
  }
}

function testDailyDigest() {
  var previous = CONFIG.DRY_RUN;
  CONFIG.DRY_RUN = true;
  try {
    var result = sendDailyDigest();
    Logger.log(JSON.stringify(result));
    return result;
  } finally {
    CONFIG.DRY_RUN = previous;
  }
}

/** Mirrors the shape Apps Script passes to a spreadsheet onFormSubmit trigger. */
function makeTestEvent_(answers) {
  var namedValues = { Timestamp: [formatDate_(new Date())] };
  Object.keys(answers).forEach(function (k) { namedValues[k] = [answers[k]]; });
  return {
    namedValues: namedValues,
    values: Object.keys(namedValues).map(function (k) { return namedValues[k][0]; }),
    range: null,
    triggerUid: 'test'
  };
}

// ---------------------------------------------------------------- helpers

function flattenNamedValues_(namedValues) {
  var out = {};
  Object.keys(namedValues).forEach(function (k) {
    var v = namedValues[k];
    out[k.trim()] = Array.isArray(v) ? v.join(', ') : String(v);
  });
  return out;
}

function buildRow_(id, received, processed, answers) {
  var known = { Timestamp: true };
  CONFIG.FIELDS.forEach(function (f) { known[f] = true; });
  var extras = Object.keys(answers)
    .filter(function (k) { return !known[k] && answers[k] !== ''; })
    .map(function (k) { return k + ': ' + answers[k]; });
  return [id, received, processed, CONFIG.STATUS_DEFAULT]
    .concat(CONFIG.FIELDS.map(function (f) { return answers[f] || ''; }))
    .concat([extras.join('\n')]);
}

function nextId_() {
  var props = PropertiesService.getScriptProperties();
  var n = Number(props.getProperty('LAST_ID') || 0) + 1;
  props.setProperty('LAST_ID', String(n));
  return CONFIG.ID_PREFIX + ('00000' + n).slice(-5);
}

function getOrCreateTab_(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold');
  }
  return sheet;
}

function uniqueTabs_() {
  var seen = {};
  var out = [];
  Object.keys(CONFIG.ROUTES).map(function (k) { return CONFIG.ROUTES[k]; })
    .concat([CONFIG.FALLBACK_TAB])
    .forEach(function (t) { if (!seen[t]) { seen[t] = true; out.push(t); } });
  return out;
}

function sendAlert_(id, tabName, answers) {
  var subject = '[High priority] ' + id + ' - ' + (answers[CONFIG.CATEGORY_FIELD] || 'Uncategorised');
  var body = CONFIG.FIELDS.map(function (f) { return f + ': ' + (answers[f] || ''); }).join('\n') +
    '\n\nFiled under tab: ' + tabName +
    '\nSheet: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl();
  send_(subject, body);
}

function send_(subject, body) {
  var to = CONFIG.ALERT_EMAIL || Session.getEffectiveUser().getEmail();
  if (CONFIG.DRY_RUN) {
    Logger.log('DRY RUN email to ' + to + '\n' + subject + '\n\n' + body);
    return;
  }
  MailApp.sendEmail(to, subject, body);
}

function indexOf_(headers) {
  var map = {};
  headers.forEach(function (h, i) { map[h] = i; });
  return map;
}

function truncate_(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n - 1) + '...' : s;
}

function formatDate_(d) {
  return Utilities.formatDate(d, CONFIG.TIMEZONE, 'yyyy-MM-dd HH:mm');
}
