# Automation Portfolio Samples

These are three small, working samples of spreadsheet and data automation. Each folder holds its code, sample input, the output that input produced, tests, and a short README.

| Sample | Stack | What it shows |
|---|---|---|
| [roster-coverage/](roster-coverage/) | Python (standard library only) | Reads a weekly shift roster and reports hourly staffing gaps against a minimum headcount, weekly hours with overtime flags, and a Markdown summary |
| [form-tracker-appsscript/](form-tracker-appsscript/) | Google Apps Script | Google Form responses get IDs and timestamps and are routed to status tabs by category. High-priority items trigger an email alert, and a daily digest goes out each morning |
| [csv-merge-dedupe/](csv-merge-dedupe/) | Python (standard library only) | Merges messy CSV exports: fuzzy header matching, value cleanup, de-duplication by email or phone, and a full change log |

## Run the tests

```bash
cd roster-coverage          && python3 -m unittest discover -s tests -v
cd ../csv-merge-dedupe      && python3 -m unittest discover -s tests -v
cd ../form-tracker-appsscript && node test/run_tests.js
```

The Apps Script sample is tested offline in Node, with stand-ins for the Google services. It has not been run inside a live Google account. Its README says exactly what was and wasn't verified.

## Data

All data here is synthetic, generated or written by hand for these samples. It does not describe real people, clients or businesses.
