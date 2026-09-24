#!/usr/bin/env python3
"""Generate a synthetic weekly shift roster (sample_input.csv).

All names are randomly assembled from generic first/last name lists.
The data is fictional and seeded, so the output is reproducible.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery",
         "Quinn", "Parker", "Drew", "Skyler", "Reese", "Rowan", "Emerson", "Hayden",
         "Kendall", "Logan", "Peyton", "Sawyer", "Blake", "Cameron", "Dakota",
         "Elliot", "Finley"]
LAST = ["Rivera", "Chen", "Patel", "Okafor", "Novak", "Silva", "Kim", "Larsen",
        "Haddad", "Moreau", "Tanaka", "Walsh", "Fischer", "Costa", "Byrne",
        "Ivanova", "Mendez", "Olsen", "Park", "Reyes", "Schmidt", "Adeyemi",
        "Lindqvist", "Duarte", "Nakamura"]

LOCATIONS = ["Northside", "Riverside"]
WEEK_START = date(2026, 9, 14)  # a Monday
# (start, end) shift templates; the store is open 06:00-22:00
TEMPLATES = [("06:00", "14:00"), ("06:00", "12:00"), ("10:00", "18:00"),
             ("12:00", "20:00"), ("14:00", "22:00"), ("16:00", "22:00")]


def main(path: Path = Path(__file__).parent / "sample_input.csv") -> None:
    rng = random.Random(2026)
    names = [f"{f} {l}" for f, l in zip(FIRST, rng.sample(LAST, len(LAST)))]
    staff = []
    for i, name in enumerate(names):
        role = "Supervisor" if i < 4 else ("Associate" if i < 19 else "Trainee")
        staff.append((name, role, LOCATIONS[i % 2]))

    rows = []
    for name, role, loc in staff:
        # Two people are deliberately over-scheduled to exercise overtime flags.
        n_days = 6 if name in (names[0], names[5]) else rng.choice([3, 4, 4, 5, 5])
        days = sorted(rng.sample(range(7), n_days))
        for d in days:
            if name in (names[0], names[5]):
                start, end = "06:00", "14:00"
            else:
                start, end = rng.choice(TEMPLATES)
            rows.append([name, role, (WEEK_START + timedelta(days=d)).isoformat(),
                         start, end, loc])
    rows.sort(key=lambda r: (r[2], r[5], r[3], r[0]))
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["employee", "role", "date", "start", "end", "location"])
        w.writerows(rows)
    print(f"Wrote {len(rows)} shifts for {len(staff)} employees to {path}")


if __name__ == "__main__":
    main()
