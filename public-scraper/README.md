# Public Scraper (polite, robots-aware, to CSV)

A Python command-line tool that collects book listings from a public catalogue, follows its "next" links page by page, and writes one clean CSV row per book.

The target is [books.toscrape.com](https://books.toscrape.com/), a sandbox that Zyte runs specifically for scraping practice ("We love being scraped!"). Its prices and ratings are made up. The parser is written for that site's markup, and an allow-list makes the script refuse any other site.

Built with AI assistance, reviewed and tested by Noah.

## How it behaves

- **Checks robots.txt first.** A rule that disallows a page stops the run before that page is requested. A missing robots.txt allows everything, as the standard says. If robots.txt can't be reached at all, the script fails closed and fetches nothing.
- **Polite pace.** It waits 1.5 seconds between pages by default (never less than 1), sends an honest User-Agent that links back to this repository, and stops at `--max-pages` (default 10).
- **Allow-list.** Only hosts in `ALLOWED_HOSTS` are fetched, including when following a "next" link. Adding a site is a deliberate edit, made only after reading its terms of service.
- **Clean output.** Full titles come from the link's title attribute (listing pages cut long titles short). Prices become plain numbers, star ratings become 1 to 5, relative links become full URLs, and a book seen twice is written once.
- **Clear stops.** An HTTP error or a network error ends the run with a message. The rows collected so far are still written.

It uses only the Python 3 standard library.

## Usage

```bash
python3 scrape_books.py https://books.toscrape.com/catalogue/category/books/mystery_3/index.html \
    -o output/mystery_books.csv
```

```
  page 1: 20 books (0 already seen)
  page 2: 12 books (0 already seen)
32 books from 2 page(s) in Mystery -> output/mystery_books.csv
```

`output/mystery_books.csv` is the result of that one live run (32 books, matching the "32 results" the site shows):

```
title,price_gbp,rating,in_stock,product_url,source_page
Sharp Objects,47.82,4,yes,https://books.toscrape.com/catalogue/sharp-objects_997/index.html,https://books.toscrape.com/...
"In a Dark, Dark Wood",19.63,1,yes,https://books.toscrape.com/catalogue/in-a-dark-dark-wood_963/index.html,https://books.toscrape.com/...
```

On macOS with the python.org installer, run "Install Certificates.command" once if you see `CERTIFICATE_VERIFY_FAILED`. The script then stops safely, because it can't read robots.txt.

## What this sample doesn't do (on purpose)

- No logins, no CAPTCHAs, no bypassing blocks or rate limits.
- No personal data. Listings are products, not people.
- No sites whose terms forbid scraping. When a site offers an API or a data export, use that instead.

## Tests

```bash
pip install -r requirements.txt   # pytest
python3 -m pytest -q
```

The 11 tests run offline against two listing pages saved from the site (`tests/fixtures/`), with a fake fetcher that records every request. They cover parsing (titles, prices, ratings, stock, full URLs), following "next" links to all 32 books, the wait between pages, the page limit, a robots.txt that disallows the path (no page is fetched), an unreachable robots.txt (fails closed), refusing a host that isn't on the allow-list before any request, stopping on an HTTP error, CSV quoting, and the saved pages reproducing the committed output.

**What was and wasn't verified:** the scraper was run once against the live sandbox on 2026-09-24 (2 pages, 3 requests including robots.txt). The tests never touch the network.

## Data

The fixtures and the output are copies of a public practice site whose content is made up by its owner for scraping practice. They contain no personal data.
