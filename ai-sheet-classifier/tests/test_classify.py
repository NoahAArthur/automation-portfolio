"""Offline tests for classify.py. No API key, no network, no anthropic package needed.

The HTTP layer is replaced by FakeClient, which returns scripted replies or
raises scripted errors shaped like the SDK's (a status_code attribute and an
optional response.headers).
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import classify as c  # noqa: E402

FAKE_KEY = "test-key-not-real-0123456789"
GOOD = {"category": "billing", "sentiment": "negative", "summary": "Customer was charged twice and wants a refund."}


def reply(obj=None, text=None, stop_reason="end_turn"):
    body = text if text is not None else json.dumps(obj)
    return SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=body),
    ])


class FakeAPIError(Exception):
    def __init__(self, status_code, message="error", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


class APIConnectionError(Exception):
    """Same class name as the SDK's, no status code."""


class FakeClient:
    def __init__(self, script=None, default=None):
        self.script = list(script or [])
        self.default = default if default is not None else reply(GOOD)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, Exception):
            raise item
        return item


class ParsingTests(unittest.TestCase):
    def test_valid_json_is_normalised(self):
        r, err = c.parse_classification('{"category":" Bug ","sentiment":"NEGATIVE","summary":"Export\\nbutton   fails."}')
        self.assertIsNone(err)
        self.assertEqual(r, {"category": "bug", "sentiment": "negative", "summary": "Export button fails."})

    def test_bad_shapes_fall_back_to_needs_review(self):
        bad = [
            "not json at all",
            '```json\n{"category":"bug"}\n```',
            "[1, 2]",
            '{"category":"bug","sentiment":"negative"}',
            '{"category":"bug","sentiment":"negative","summary":"x","extra":1}',
            '{"category":"refund","sentiment":"negative","summary":"x"}',
            '{"category":"bug","sentiment":"angry","summary":"x"}',
            '{"category":"bug","sentiment":"negative","summary":"   "}',
            '{"category":7,"sentiment":"negative","summary":"x"}',
        ]
        for b in bad:
            with self.subTest(b=b):
                r, err = c.parse_classification(b)
                self.assertEqual(r["category"], c.NEEDS_REVIEW)
                self.assertEqual(r["sentiment"], c.NEEDS_REVIEW)
                self.assertTrue(err)

    def test_long_summary_trimmed(self):
        r, _ = c.parse_classification(json.dumps({"category": "other", "sentiment": "neutral", "summary": "word " * 100}))
        self.assertLessEqual(len(r["summary"]), c.SUMMARY_MAX_CHARS)

    def test_refusal_and_max_tokens(self):
        for stop in ("refusal", "max_tokens"):
            with self.subTest(stop=stop):
                r, err = c.parse_response(reply(GOOD, stop_reason=stop))
                self.assertEqual(r["category"], c.NEEDS_REVIEW)
                self.assertIn(stop, err)

    def test_no_text_block(self):
        r, err = c.parse_response(SimpleNamespace(stop_reason="end_turn", content=[]))
        self.assertEqual(r["category"], c.NEEDS_REVIEW)


class RequestShapeTests(unittest.TestCase):
    def test_model_schema_and_fallback(self):
        client = FakeClient()
        c.classify_text(client, "hello", sleep=lambda s: None, model="claude-opus-5")
        kw = client.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5")
        fmt = kw["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertFalse(fmt["schema"]["additionalProperties"])
        self.assertEqual(kw["output_config"]["effort"], "low")
        self.assertEqual(kw["extra_body"], {"fallbacks": "default"})
        self.assertEqual(kw["extra_headers"], {"anthropic-beta": "server-side-fallback-2026-07-01"})
        self.assertIn("hello", kw["messages"][0]["content"])

    def test_haiku_drops_effort_and_fallback(self):
        client = FakeClient()
        c.classify_text(client, "hello", sleep=lambda s: None, model="claude-haiku-4-5")
        kw = client.calls[0]
        self.assertEqual(kw["model"], "claude-haiku-4-5")
        self.assertNotIn("effort", kw["output_config"])
        self.assertNotIn("extra_body", kw)


class RetryTests(unittest.TestCase):
    def test_retries_429_and_5xx_then_succeeds(self):
        client = FakeClient([FakeAPIError(429), FakeAPIError(529), APIConnectionError("reset"), reply(GOOD)])
        sleeps = []
        r, err = c.classify_text(client, "hi", sleep=sleeps.append)
        self.assertIsNone(err)
        self.assertEqual(r["category"], "billing")
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(sleeps[0] >= 1 and sleeps[1] >= 2 and sleeps[2] >= 4, sleeps)

    def test_retry_after_header_is_honoured(self):
        client = FakeClient([FakeAPIError(429, headers={"retry-after": "7"}), reply(GOOD)])
        sleeps = []
        c.classify_text(client, "hi", sleep=sleeps.append)
        self.assertEqual(sleeps, [7.0])

    def test_gives_up_after_max_retries(self):
        client = FakeClient(default=FakeAPIError(503, "unavailable"))
        r, err = c.classify_text(client, "hi", sleep=lambda s: None)
        self.assertEqual(len(client.calls), c.MAX_RETRIES + 1)
        self.assertEqual(r["category"], c.NEEDS_REVIEW)
        self.assertIn("HTTP 503", err)

    def test_400_not_retried(self):
        client = FakeClient([FakeAPIError(400, "bad request")])
        sleeps = []
        r, err = c.classify_text(client, "hi", sleep=sleeps.append)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(r["category"], c.NEEDS_REVIEW)


class CsvRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "out.csv"
        self.log = self.tmp / "log.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text):
        p = self.tmp / "in.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def read(self, p):
        with p.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def run_csv(self, path, client, **kw):
        return c.classify_csv(path, self.out, self.log, client, sleep=lambda s: None, api_key=FAKE_KEY, **kw)

    def test_sample_file_end_to_end(self):
        sample = HERE.parent / "sample_feedback.csv"
        client = FakeClient()
        counts = self.run_csv(sample, client)
        rows = self.read(self.out)
        self.assertEqual(len(rows), 20)
        self.assertEqual(counts["classified"], 20)
        self.assertEqual(len(client.calls), 20)
        self.assertEqual(list(rows[0].keys())[-3:], ["category", "sentiment", "summary"])
        self.assertFalse(self.log.exists(), "no log when nothing went wrong")

    def test_skips_already_classified_and_empty_rows(self):
        p = self.write("id,message,category,sentiment,summary\n"
                       "1,Already done,bug,neutral,Old summary\n"
                       "2,,,,\n"
                       "3,New message,,,\n"
                       "4,Flagged before,needs review,needs review,\n")
        client = FakeClient()
        counts = self.run_csv(p, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(counts["skipped"], 3)
        rows = self.read(self.out)
        self.assertEqual(rows[0]["summary"], "Old summary")
        self.assertEqual(rows[2]["category"], "billing")

    def test_output_can_be_fed_back_in_to_resume(self):
        p = self.write("id,message\n1,first\n2,second\n")
        self.run_csv(p, FakeClient(), limit=1)
        resumed = self.tmp / "resumed.csv"
        client = FakeClient()
        c.classify_csv(self.out, resumed, self.log, client, sleep=lambda s: None, api_key=FAKE_KEY)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("second", client.calls[0]["messages"][0]["content"])
        self.assertTrue(all(r["category"] == "billing" for r in self.read(resumed)))

    def test_bad_json_becomes_needs_review_and_is_logged(self):
        p = self.write("id,message\n1,a\n2,b\n3,c\n")
        client = FakeClient([reply(text="Sure! Category: billing"), reply(GOOD), reply(text='{"category":"billing"')])
        counts = self.run_csv(p, client)
        self.assertEqual(counts["needs_review"], 2)
        rows = self.read(self.out)
        self.assertEqual([r["category"] for r in rows], ["needs review", "billing", "needs review"])
        log = self.read(self.log)
        self.assertEqual([r["row"] for r in log], ["2", "4"])

    def test_case_insensitive_column_and_missing_column(self):
        p = self.write("id,Message\n1,hello\n")
        self.run_csv(p, FakeClient())
        self.assertEqual(self.read(self.out)[0]["category"], "billing")
        with self.assertRaises(SystemExit):
            self.run_csv(p, FakeClient(), column="text")

    def test_key_never_logged_or_written(self):
        p = self.write("id,message\n1,a\n2,b\n3,c\n")
        client = FakeClient([
            FakeAPIError(401, f"invalid x-api-key: {FAKE_KEY}"),
            FakeAPIError(400, "key sk-ant-api03-EXAMPLEONLY rejected"),
            reply(GOOD),
        ])
        self.run_csv(p, client)
        everything = self.log.read_text() + self.out.read_text()
        self.assertNotIn(FAKE_KEY, everything)
        self.assertNotIn("sk-ant-api03", everything)
        self.assertIn("[redacted]", self.log.read_text())

    def test_no_hard_coded_key_in_source(self):
        import re
        src = (HERE.parent / "classify.py").read_text()
        self.assertIsNone(re.search(r"sk-ant-[A-Za-z0-9]{10,}", src))

    def test_estimate_runs_without_api(self):
        text = c.estimate(HERE.parent / "sample_feedback.csv", "message")
        self.assertIn("20 rows to classify", text)
        self.assertIn("claude-haiku-4-5", text)


if __name__ == "__main__":
    unittest.main()
