import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import merge_dedupe as md  # noqa: E402


class HeaderMappingTests(unittest.TestCase):
    def test_exact_and_fuzzy(self):
        self.assertEqual(md.map_header("E-mail")[0], "email")
        self.assertEqual(md.map_header(" Email Address ")[0], "email")
        self.assertEqual(md.map_header("phone #")[0], "phone")
        self.assertEqual(md.map_header("Organisation")[0], "company")
        field, how = md.map_header("emial")  # typo
        self.assertEqual(field, "email")
        self.assertTrue(how.startswith("fuzzy"))

    def test_unrelated_column_is_not_guessed(self):
        self.assertIsNone(md.map_header("Signup Source")[0])


class NormaliserTests(unittest.TestCase):
    def test_phone_formats(self):
        for raw in ["(555) 010-1001", "555.010.1001", "5550101001", "+1 555 010 1001",
                    "1-555-010-1001", "555/010/1001"]:
            self.assertEqual(md.norm_phone(raw), ("(555) 010-1001", None), raw)
        self.assertIsNotNone(md.norm_phone("12345")[1])

    def test_email(self):
        self.assertEqual(md.norm_email("  Jo.Doe@Example.COM "), ("jo.doe@example.com", None))
        self.assertIsNotNone(md.norm_email("jo@example")[1])

    def test_names(self):
        self.assertEqual(md.fix_case("OYELARAN"), "Oyelaran")
        self.assertEqual(md.fix_case("  marcus "), "Marcus")
        self.assertEqual(md.fix_case("McKenna"), "McKenna")
        self.assertEqual(md.split_full_name("Liu, Grace"), ("Grace", "Liu"))
        self.assertEqual(md.split_full_name("Beatriz  Moreno"), ("Beatriz", "Moreno"))


class EndToEndTests(unittest.TestCase):
    def test_sample_inputs(self):
        inputs = sorted((HERE.parent / "input").glob("*.csv"))
        self.assertEqual(len(inputs), 3)
        with tempfile.TemporaryDirectory() as tmp:
            out, log = Path(tmp) / "merged.csv", Path(tmp) / "log.csv"
            stats = md.run(inputs, out, log)
            with out.open() as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(stats["rows_in"], 21)       # 22 data rows minus 1 blank
        self.assertEqual(len(rows), 13)              # unique people
        emails = [r["email"] for r in rows if r["email"]]
        self.assertEqual(len(emails), len(set(emails)), "duplicate email in output")
        grace = next(r for r in rows if r["last_name"] == "Liu")
        self.assertEqual(grace["email"], "grace.liu@example.com")  # merged via phone
        self.assertEqual(len(grace["sources"].split(";")), 2)
        owen = next(r for r in rows if r["last_name"] == "Brandt")
        self.assertEqual(owen["phone"], "(555) 010-1006")           # blank filled
        kofi = next(r for r in rows if r["last_name"] == "Mensah")
        self.assertIn("invalid email", kofi["issues"])

    def test_merge_is_transitive(self):
        recs = []
        log = md.Log()
        for origin, email, phone in [("t.csv:2", "x@example.com", ""),
                                     ("t.csv:3", "x@example.com", "(555) 010-2000"),
                                     ("t.csv:4", "", "(555) 010-2000")]:
            r = {f: "" for f in md.SCHEMA}
            r.update(email=email, phone=phone, _origin=origin, _issues=[],
                     _email_ok=bool(email), _phone_ok=bool(phone))
            recs.append(r)
        self.assertEqual(len(md.dedupe(recs, log)), 1)


if __name__ == "__main__":
    unittest.main()
