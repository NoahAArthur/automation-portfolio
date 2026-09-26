# Automation Portfolio Samples

These are six small, working samples of spreadsheet, data, reporting and AI automation. Each folder holds its code, sample input, the output that input produced, tests, and a short README.

| Sample | Stack | What it shows |
|---|---|---|
| [roster-coverage/](roster-coverage/) | Python (standard library only) | Reads a weekly shift roster and reports hourly staffing gaps against a minimum headcount, weekly hours with overtime flags, and a Markdown summary |
| [form-tracker-appsscript/](form-tracker-appsscript/) | Google Apps Script | Google Form responses get IDs and timestamps and are routed to status tabs by category. High-priority items trigger an email alert, and a daily digest goes out each morning |
| [csv-merge-dedupe/](csv-merge-dedupe/) | Python (standard library only) | Merges messy CSV exports: fuzzy header matching, value cleanup, de-duplication by email or phone, and a full change log |
| [ai-sheet-classifier/](ai-sheet-classifier/) | Google Apps Script + Python, Claude API | A Sheets menu that sends selected rows to Claude and writes back a category, sentiment and one-line summary. It uses strict JSON with a "needs review" fallback, retries with backoff, skips rows already done, and keeps a Log tab. A Python version does the same for CSV files |
| [sales-dashboard/](sales-dashboard/) | Python + openpyxl | Turns a sales CSV into a one-file HTML dashboard (headline numbers, 4 colorblind-safe charts, data tables, light and dark mode) and an Excel report with 4 native charts |
| [public-scraper/](public-scraper/) | Python (standard library only) | Collects listings from a public scraping sandbox into a CSV, following page links, with robots.txt checks, a polite delay, and a host allow-list |

## Run the tests

```bash
cd roster-coverage          && python3 -m unittest discover -s tests -v
cd ../csv-merge-dedupe      && python3 -m unittest discover -s tests -v
cd ../form-tracker-appsscript && node test/run_tests.js
cd ../ai-sheet-classifier   && node test/run_tests.js && python3 -m unittest discover -s tests -v
cd ../sales-dashboard       && pip install -r requirements.txt && python3 -m pytest -q
cd ../public-scraper        && python3 -m pytest -q
```

The Apps Script samples are tested offline in Node, with stand-ins for the Google services. They have not been run inside a live Google account. The AI classifier's tests fake the Claude API too, so they need no API key. It has not been run against the live API yet. Each README says exactly what was and wasn't verified.

## Data

All data here is synthetic, generated or written by hand for these samples. It does not describe real people, clients or businesses. The one exception is `public-scraper/`, whose pages come from books.toscrape.com, a practice site built for scraping whose books, prices and ratings are made up by its owner.
