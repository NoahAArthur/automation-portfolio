import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import roster_coverage as rc  # noqa: E402

HEADER = "employee,role,date,start,end,location\n"


def write(tmp: Path, body: str) -> Path:
    p = tmp / "roster.csv"
    p.write_text(HEADER + body)
    return p


class RosterCoverageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_headcount_and_gap_flag(self):
        path = write(self.tmp,
                     "A,Associate,2026-09-14,08:00,12:00,Main\n"
                     "B,Associate,2026-09-14,08:00,10:00,Main\n")
        shifts, problems = rc.load_shifts(path)
        self.assertEqual(problems, [])
        cov = {r[2]: r for r in rc.build_coverage(shifts, min_staff=2)}
        self.assertEqual(sorted(cov), [8, 9, 10, 11])
        self.assertEqual(cov[8][3], 2)
        self.assertFalse(cov[9][5])
        self.assertEqual(cov[10][3], 1)
        self.assertTrue(cov[10][5])

    def test_half_hour_presence_rule(self):
        path = write(self.tmp,
                     "A,Associate,2026-09-14,08:00,12:00,Main\n"
                     "B,Associate,2026-09-14,08:45,11:15,Main\n")
        shifts, _ = rc.load_shifts(path)
        cov = {r[2]: r[3] for r in rc.build_coverage(shifts, min_staff=1)}
        # B works only 15 min of the 08:00 and 11:00 hours, so is not counted there.
        self.assertEqual(cov, {8: 1, 9: 2, 10: 2, 11: 1})

    def test_overtime_and_overnight(self):
        body = "".join(f"A,Lead,2026-09-{14 + d},06:00,15:00,Main\n" for d in range(5))
        body += "B,Associate,2026-09-14,22:00,06:00,Main\n"
        shifts, _ = rc.load_shifts(write(self.tmp, body))
        hours = {r[0]: r for r in rc.build_hours(shifts, ot_threshold=40)}
        self.assertEqual(hours["A"][3], 45.0)
        self.assertEqual(hours["A"][4], 5.0)
        self.assertTrue(hours["A"][5])
        self.assertEqual(hours["B"][3], 8.0)
        self.assertFalse(hours["B"][5])

    def test_overnight_shift_counts_after_midnight(self):
        path = write(self.tmp, "N,Associate,2026-09-14,22:00,06:00,Main\n")
        shifts, _ = rc.load_shifts(path)
        cov = {(r[1].day, r[2]): r[3] for r in rc.build_coverage(shifts, min_staff=1)}
        self.assertEqual(cov[(14, 23)], 1)
        self.assertEqual(cov[(15, 2)], 1)
        self.assertEqual(cov[(15, 6)], 0)

    def test_bad_rows_are_reported_not_fatal(self):
        path = write(self.tmp,
                     "A,Associate,2026-09-14,08:00,12:00,Main\n"
                     "B,Associate,not-a-date,08:00,12:00,Main\n"
                     "C,Associate,2026-09-14,25:00,12:00,Main\n")
        shifts, problems = rc.load_shifts(path)
        self.assertEqual(len(shifts), 1)
        self.assertEqual(len(problems), 2)

    def test_end_to_end_on_sample(self):
        out = self.tmp / "out"
        stats = rc.run(HERE.parent / "sample_input.csv", out, min_staff=3)
        for name in ("coverage.csv", "hours.csv", "summary.md"):
            self.assertTrue((out / name).exists(), name)
        with (out / "hours.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 25)
        self.assertGreaterEqual(stats["overtime_employees"], 1)
        self.assertIn("# Roster Coverage Summary", (out / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
