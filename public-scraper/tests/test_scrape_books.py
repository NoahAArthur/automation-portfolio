"""Offline tests on saved pages: python3 -m pytest -q  (no network; fetches are faked)."""
import csv
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import scrape_books as sb  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
BASE = "https://books.toscrape.com/catalogue/category/books/mystery_3/"
PAGES = {
    BASE + "index.html": (FIX / "mystery_page1.html").read_text(encoding="utf-8"),
    BASE + "page-2.html": (FIX / "mystery_page2.html").read_text(encoding="utf-8"),
}


class FakeWeb:
    """Serves the saved pages and records every URL requested."""

    def __init__(self, robots=(404, ""), pages=PAGES):
        self.robots, self.pages, self.calls = robots, pages, []

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return self.robots
        return (200, self.pages[url]) if url in self.pages else (404, "")


def run(web, **kw):
    sleeps = []
    rows, pages, cat = sb.scrape(BASE + "index.html", fetch=web, sleep=sleeps.append, log=lambda *_: None, **kw)
    return rows, pages, cat, sleeps


def test_parses_a_listing_page():
    rows, next_url, category = sb.parse_listing(PAGES[BASE + "index.html"], BASE + "index.html")
    assert len(rows) == 20 and category == "Mystery"
    assert next_url == BASE + "page-2.html"
    assert rows[0] == {
        "title": "Sharp Objects", "price_gbp": "47.82", "rating": 4, "in_stock": "yes",
        "product_url": "https://books.toscrape.com/catalogue/sharp-objects_997/index.html",
        "source_page": BASE + "index.html",
    }
    assert rows[1]["title"] == "In a Dark, Dark Wood"  # full title from the title attribute, entities decoded


def test_every_row_is_complete():
    rows, _, _ = sb.parse_listing(PAGES[BASE + "page-2.html"], BASE + "page-2.html")
    assert len(rows) == 12
    for r in rows:
        assert r["title"] and r["rating"] in {1, 2, 3, 4, 5}
        assert float(r["price_gbp"]) > 0
        assert r["product_url"].startswith("https://books.toscrape.com/catalogue/")


def test_follows_next_links_to_the_last_page():
    web = FakeWeb()
    rows, pages, cat, sleeps = run(web)
    assert (len(rows), pages, cat) == (32, 2, "Mystery")  # the site says "32 results"
    assert len({r["product_url"] for r in rows}) == 32


def test_waits_between_pages_but_not_before_the_first():
    _, _, _, sleeps = run(FakeWeb(), delay=2.0)
    assert sleeps == [2.0]


def test_max_pages_is_respected():
    rows, pages, _, _ = run(FakeWeb(), max_pages=1)
    assert pages == 1 and len(rows) == 20


def test_robots_disallow_stops_before_any_page_is_fetched():
    web = FakeWeb(robots=(200, "User-agent: *\nDisallow: /catalogue/\n"))
    rows, pages, _, _ = run(web)
    assert rows == [] and pages == 0
    assert web.calls == ["https://books.toscrape.com/robots.txt"]


def test_unreachable_robots_txt_fails_closed():
    rows, pages, _, _ = run(FakeWeb(robots=(0, "")))
    assert rows == [] and pages == 0


def test_hosts_off_the_allow_list_are_refused():
    web = FakeWeb()
    with pytest.raises(ValueError, match="allow-list"):
        sb.scrape("https://example.com/shop", fetch=web, log=lambda *_: None)
    assert web.calls == []  # refused before any request


def test_http_error_stops_cleanly():
    pages = {BASE + "index.html": PAGES[BASE + "index.html"]}  # page 2 is "missing"
    rows, n, _, _ = run(FakeWeb(pages=pages))
    assert len(rows) == 20 and n == 2


def test_csv_output(tmp_path):
    rows, _, _, _ = run(FakeWeb())
    out = tmp_path / "books.csv"
    sb.write_csv(rows, out)
    with open(out, newline="", encoding="utf-8") as f:
        back = list(csv.DictReader(f))
    assert list(back[0]) == sb.FIELDS and len(back) == 32
    assert back[1]["title"] == "In a Dark, Dark Wood"  # comma survives CSV quoting


def test_committed_sample_output_matches_the_parser():
    """output/mystery_books.csv came from one live run; the saved pages must reproduce it."""
    rows, _, _, _ = run(FakeWeb())
    with open(HERE / "output" / "mystery_books.csv", newline="", encoding="utf-8") as f:
        committed = list(csv.DictReader(f))
    assert [r["product_url"] for r in committed] == [r["product_url"] for r in rows]
    assert [r["price_gbp"] for r in committed] == [r["price_gbp"] for r in rows]
