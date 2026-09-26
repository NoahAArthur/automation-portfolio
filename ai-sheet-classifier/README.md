# AI Sheet Classifier (Google Sheets + Claude API, with a Python CSV twin)

Select rows in a Google Sheet, click **AI Classifier > Classify selected rows**, and each row's message (a support email, a review, a feedback form answer) is sent to the Claude API. Three columns come back:

| Column | Values |
|---|---|
| Category | `billing`, `bug`, `feature_request`, `account`, `shipping`, `praise`, `other` (edit the list in `CONFIG`) |
| Sentiment | `positive`, `neutral`, `negative` |
| Summary | One plain sentence saying what the customer wants or reports |

`classify.py` does the same job for a CSV file, for teams that work from exports instead of a Sheet.

Built with AI assistance, reviewed and tested by Noah.

## How it behaves

- **Key stays out of the sheet and the code.** The Apps Script reads the API key from Script Properties (the menu has a "Set API key" item). The Python script reads `ANTHROPIC_API_KEY` from the environment. The key is scrubbed from every log line.
- **Strict JSON, checked twice.** The request uses the API's JSON-schema output format, so the model has to answer with exactly `category`, `sentiment` and `summary`, with categories limited to the list. The script then validates the reply again. Anything that doesn't pass (bad JSON, an unknown category, an empty summary, a refusal, a cut-off reply) is written as **`needs review`**, never a guess.
- **Batches and retries.** The Apps Script sends 10 rows at a time in parallel. Rate limits (429), overloads (529) and server errors (5xx) are retried up to 4 times with exponential backoff (1s, 2s, 4s, 8s). If the API sends a `retry-after` header, the script waits that long instead. Only the rows that failed are retried. Other errors, such as a bad key, are not retried.
- **Safe to re-run.** Rows that already have a Category are skipped, so you can run it again on the same selection, or feed the Python output back in, to finish an interrupted run without paying twice. To redo a row, clear its Category cell.
- **Log tab.** Every problem is written to a `Log` tab (time, sheet, row, level, message). The Python version writes `<output>_log.csv`.
- **Time limit.** Apps Script stops a run after 6 minutes. The script stops itself at 5 minutes, logs that it did, and the next run picks up where it stopped.
- **Prompt injection.** The message is wrapped as data, and the prompt tells the model to classify it whatever it says. Sample row FB-017 tries this.

The default model is `claude-haiku-4-5`. Classification is a simple task, so the cheapest model is enough (about $0.65–1.10 per 1,000 rows). For harder or messier text, set `MODEL` to `claude-sonnet-5` or `claude-opus-5`. On those larger models the script also sends `effort: low` and turns on Anthropic's server-side refusal fallback (`fallbacks: "default"`). Haiku doesn't accept either.

## Setup (Google Sheets)

1. Create an API key in the [Anthropic Console](https://platform.claude.com/) and **set a monthly spend limit** on it.
2. Open your Sheet. Row 1 needs a `Message` column header. Any other columns are left alone. Open **Extensions > Apps Script**, paste in `Code.gs`, and save. Optional: turn on "Show appsscript.json" in Project Settings and paste in `appsscript.json`.
3. Reload the Sheet. An **AI Classifier** menu appears. Choose **Set API key**, paste the key, and approve the permissions Google asks for.
4. Select a few rows and choose **Classify selected rows**. Category, Sentiment and Summary columns are added if they don't exist.
5. Check the results and the `Log` tab. Then adjust `CONFIG.CATEGORIES` (and `TEXT_HEADER` if your column has another name) to fit your data.

## Python CSV version

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...                     # your key; never commit it
python3 classify.py sample_feedback.csv --estimate          # cost estimate, no API calls
python3 classify.py sample_feedback.csv --limit 5           # cheap trial run
python3 classify.py sample_feedback.csv -o classified.csv   # full run
```

Options: `--column` (text column, default `message`), `--model`, `--log`, `--limit`. The output keeps every input column and adds `category`, `sentiment` and `summary`.

## Cost per 1,000 rows

Prices are Anthropic's published standard API rates, from the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-09-24. Assumptions: about 350 input tokens per row (the fixed prompt and schema plus a short message) and about 150 output tokens (the JSON plus a little thinking at low effort). Long messages cost more. Re-check the prices before quoting a client.

| Model | Input / output price per million tokens | Approx. cost per 1,000 rows |
|---|---|---|
| Claude Opus 5 | $5 / $25 | about $5.50 |
| Claude Sonnet 5 | $2 / $10 | about $2.20 |
| Claude Haiku 4.5 (default) | $1 / $5 | about $0.65 to $1.10 |

`python3 classify.py your_file.csv --estimate` gives a figure for your own file. Anthropic's Batch API is half price, but results come back asynchronously, so this sample doesn't use it.

## Limitations

- **Tested offline only.** The tests replace the HTTP layer with fakes. Neither version has been run against the live Claude API, and `Code.gs` has not run inside a real Google account. The request shape follows Anthropic's documentation, but nothing here proves a live call works.
- The model can still be wrong, especially on short or mixed messages (sample FB-018 is just "ok"). Keep a person reviewing anything that reaches customers.
- The message text goes to Anthropic under the key owner's account and API data terms. Don't send data your policies don't allow.
- Messages over 8,000 characters are marked `needs review` and not sent, rather than being cut short.
- The Apps Script processes the rows you select. It doesn't run on a trigger, and one run handles about 5 minutes of rows.
- The Python version sends one row at a time, which is simple but slower on big files.

## Tests (no API key needed)

```bash
node test/run_tests.js                        # Apps Script logic: 22 tests (Node 18+, no dependencies)
python3 -m unittest discover -s tests -v      # Python: 19 tests (the anthropic package is not needed)
```

They cover JSON parsing and validation, the request shape (model, schema, key only in the header), batching, retry and backoff on 429, 529, 5xx and connection errors, `retry-after`, no retry on 400, skipping rows already done, resuming, the `needs review` fallback for bad JSON, refusals and cut-off replies, the Log tab, and that the key never shows up in the sheet, the log or the output.

## Files

- `Code.gs`: the Apps Script
- `appsscript.json`: project manifest (V8 runtime)
- `classify.py`: the Python CSV version
- `sample_feedback.csv`: 20 invented customer messages. No real people or companies.
- `test/run_tests.js`: offline Node harness for `Code.gs`, with stand-ins for SpreadsheetApp, UrlFetchApp and the other services
- `tests/test_classify.py`: offline unittest suite for `classify.py`, with a fake client
