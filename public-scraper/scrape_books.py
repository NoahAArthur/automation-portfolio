"""Polite scraper for a public practice site, written to CSV.

    python3 scrape_books.py https://books.toscrape.com/catalogue/category/books/mystery_3/index.html \
        -o output/mystery_books.csv

Target: books.toscrape.com, a sandbox run by Zyte specifically for scraping practice
("We love being scraped!"; its prices and ratings are made up). The parser is written for
that site's markup, and the host allow-list refuses anything else. For a real client site
the approach is the same, but only after checking its terms of service and robots.txt, and
never behind a login or for personal data.

Polite by default: checks robots.txt before every page, identifies itself with a
User-Agent, waits between requests (--delay, default 1.5 s), and stops at --max-pages.
Uses only the Python standard library.
"""
import argparse
import csv
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ALLOWED_HOSTS = {"books.toscrape.com"}
USER_AGENT = "automation-portfolio-sample/1.0 (+https://github.com/NoahAArthur/automation-portfolio)"
RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
FIELDS = ["title", "price_gbp", "rating", "in_stock", "product_url", "source_page"]


class ListingParser(HTMLParser):
    """Pulls each <article class="product_pod"> and the "next" link from a listing page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.books, self.next_href, self.category = [], None, None
        self._book = None
        self._field = None       # which text we are collecting: price / stock
        self._in_next = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "article" and "product_pod" in classes:
            self._book = {"title": "", "href": "", "price": "", "rating": "", "stock": ""}
            return
        if tag == "li" and "next" in classes:
            self._in_next = True
        elif tag == "a" and self._in_next and self.next_href is None:
            self.next_href = a.get("href")
        elif tag == "h1":
            self._in_h1 = True
        if self._book is None:
            return
        if tag == "p" and "star-rating" in classes:
            self._book["rating"] = next((c for c in classes if c in RATINGS), "")
        elif tag == "p" and "price_color" in classes:
            self._field = "price"
        elif tag == "p" and "availability" in classes:
            self._field = "stock"
        elif tag == "a" and a.get("title"):  # the <h3><a title="Full Title"> link
            self._book["title"] = a["title"]
            self._book["href"] = a.get("href", "")

    def handle_endtag(self, tag):
        if tag == "li":
            self._in_next = False
        if tag == "h1":
            self._in_h1 = False
        if self._book is None:
            return
        if tag == "p":
            self._field = None
        if tag == "article":  # listing articles are never nested
            self.books.append(self._book)
            self._book = None

    def handle_data(self, data):
        if self._in_h1 and data.strip():
            self.category = data.strip()
        if self._book is not None and self._field:
            self._book[self._field] += data


def parse_listing(html_text, page_url):
    """Returns (rows, next_url, category). Rows are clean dicts ready for the CSV."""
    p = ListingParser()
    p.feed(html_text)
    rows = []
    for b in p.books:
        price = b["price"].strip().lstrip("Â").replace("£", "").replace(",", "")
        rows.append({
            "title": " ".join(b["title"].split()),
            "price_gbp": f"{float(price):.2f}" if price else "",
            "rating": RATINGS.get(b["rating"], ""),
            "in_stock": "yes" if "in stock" in b["stock"].lower() else "no",
            "product_url": urljoin(page_url, b["href"]),
            "source_page": page_url,
        })
    next_url = urljoin(page_url, p.next_href) if p.next_href else None
    return rows, next_url, p.category


# ---------------------------------------------------------------- fetching

def http_get(url, timeout=20):
    """Returns (status, text). Network errors become status 0."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  network error for {url}: {e}", file=sys.stderr)
        return 0, ""


def robots_checker(start_url, fetch):
    """Reads robots.txt once. A missing robots.txt (4xx) allows all; an unreachable one denies all."""
    root = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    status, text = fetch(root + "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    if 200 <= status < 300:
        rp.parse(text.splitlines())
    elif 400 <= status < 500:
        rp.allow_all = True
    else:
        rp.disallow_all = True
    return lambda url: rp.can_fetch(USER_AGENT, url)


def scrape(start_url, fetch=http_get, max_pages=10, delay=1.5, sleep=time.sleep, log=print):
    host = urlparse(start_url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"{host} is not on the allow-list ({', '.join(sorted(ALLOWED_HOSTS))}). "
                         "Check the site's terms and robots.txt before adding it.")
    allowed = robots_checker(start_url, fetch)
    rows, seen, url, pages, category = [], set(), start_url, 0, None
    while url and pages < max_pages:
        if urlparse(url).hostname not in ALLOWED_HOSTS:
            log(f"  stopping: next page {url} is off the allow-list")
            break
        if not allowed(url):
            log(f"  stopping: robots.txt disallows {url}")
            break
        if pages:
            sleep(delay)
        status, text = fetch(url)
        pages += 1
        if status != 200:
            log(f"  stopping: HTTP {status} for {url}")
            break
        page_rows, url, cat = parse_listing(text, url)
        category = category or cat
        new = [r for r in page_rows if r["product_url"] not in seen]
        seen.update(r["product_url"] for r in new)
        rows.extend(new)
        log(f"  page {pages}: {len(page_rows)} books ({len(page_rows) - len(new)} already seen)")
    return rows, pages, category


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Polite scraper for books.toscrape.com listing pages -> CSV")
    ap.add_argument("start_url")
    ap.add_argument("-o", "--out", default="output/books.csv")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between page requests (min 1)")
    a = ap.parse_args(argv)
    rows, pages, category = scrape(a.start_url, max_pages=a.max_pages, delay=max(a.delay, 1.0))
    write_csv(rows, a.out)
    print(f"{len(rows)} books from {pages} page(s){f' in {category}' if category else ''} -> {a.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
