# Google Form Request Tracker (Apps Script)

This Apps Script attaches to the Google Sheet that collects a Google Form's responses. It does four things:

- **Routes each response** to a tab based on its Category (Billing, Technical, and so on). Anything it doesn't recognise goes to an `Other` tab. Tabs are created with headers the first time they're needed.
- **Stamps each response** with an ID (`REQ-00001`, …) and a processed timestamp, and sets its status to `New`. A script lock keeps IDs unique even when two responses arrive at the same moment.
- **Emails an alert** when the Priority answer is High, whatever the capitalisation.
- **Sends a daily digest** email with new and open requests per tab, plus a list of the High-priority items from the last 24 hours.

Form questions that aren't among the tracked columns are saved in a `Details` column, so no answers are lost.

## Setup

1. Create a Google Form with at least **Category** and **Priority** questions. Name, Email and Description are optional. Link it to a spreadsheet: in the form, open Responses and choose Link to Sheets.
2. In that spreadsheet, open **Extensions > Apps Script**. Replace the contents of `Code.gs` with this project's `Code.gs`.
3. Optional: open Project Settings and turn on "Show appsscript.json". Paste in this project's `appsscript.json` to set the timezone and the V8 runtime.
4. Edit `CONFIG` at the top of `Code.gs` to set category routes, column names, the alert email (blank sends to you), and the hour the digest goes out.
5. Run **`testHandleFormSubmit`** once from the editor and grant the permissions Google asks for. It creates the tabs, writes two sample rows, and logs the alert email instead of sending it.
6. Run **`installTriggers`** once. This sets up the form-submit trigger and the daily digest trigger. Running it again replaces them rather than creating duplicates.
7. Delete the two test rows. They are marked with `REQ-00001` and `REQ-00002`.

## Functions

| Function | Purpose |
|---|---|
| `handleFormSubmit(e)` | Runs on every form submission (installable trigger) |
| `sendDailyDigest()` | Sends the daily summary email (time-driven trigger) |
| `installTriggers()` | Creates both triggers; safe to run again |
| `testHandleFormSubmit()` | Builds a fake form-submit event and runs the handler with emails logged instead of sent |
| `testDailyDigest()` | Runs the digest with emails logged instead of sent |

## What was and wasn't tested

**Tested, offline:**

- **Syntax.** `Code.gs` parses as JavaScript. Both of these commands pass:
  - `node --check` on a `.js` copy of the file
  - `node -e "new (require('vm').Script)(require('fs').readFileSync('Code.gs','utf8'))"`
- **Logic.** `test/run_tests.js` loads `Code.gs` into Node with small in-memory stand-ins for `SpreadsheetApp`, `MailApp`, `LockService`, `PropertiesService`, `ScriptApp`, `Session`, `Logger` and `Utilities`. It then runs the script's own test functions. All 6 tests pass: routing and the fallback tab, ID sequence, headers, the Details column, High-only alerts, dry-run behaviour, digest counts, and trigger setup being safe to run twice.

  ```bash
  node test/run_tests.js      # Node 18+, no dependencies
  ```

**Not tested:**

- The script has not run inside Google Apps Script or against a real Sheet, Form or Gmail account. The stand-ins copy the documented API shapes, but they are not Google's services.
- The permissions prompt, real trigger firing, `MailApp` quotas, and how Sheets formats dates in cells.
- Timezone handling. The stand-in `Utilities.formatDate` ignores timezones. In production, set the project timezone in `appsscript.json` to match `CONFIG.TIMEZONE`.

## Files

- `Code.gs`: the script
- `appsscript.json`: the project manifest (timezone and V8 runtime)
- `test/run_tests.js`: the offline test harness (Node only, not part of the Apps Script project)
