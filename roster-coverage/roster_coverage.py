#!/usr/bin/env python3
"""Roster coverage and overtime report.

Reads a weekly shift-roster CSV (employee, role, date, start, end, location)
and writes:
  coverage.csv      per location, per day, per hour headcount with a below-minimum flag
  hours.csv         per-employee weekly hours with an overtime flag
  summary.md        a readable report of gaps, overtime and skipped rows

Standard library only (Python 3.8+).

Usage:
  python3 roster_coverage.py sample_input.csv --out output --min-staff 3
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

REQUIRED = ["employee", "role", "date", "start", "end", "location"]
# A person counts toward an hour's headcount if they work at least this many
# minutes of that clock hour (e.g. a 10:30 start counts for the 10:00 hour).
PRESENCE_MINUTES = 30


@dataclass
class Shift:
    employee: str
    role: str
    location: str
    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def parse_time(day: date, value: str) -> datetime:
    value = value.strip().upper()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H%M"):
        try:
            t = datetime.strptime(value, fmt).time()
            return datetime.combine(day, t)
        except ValueError:
            continue
    raise ValueError(f"unrecognised time '{value}'")


def load_shifts(path: Path) -> tuple[list[Shift], list[str]]:
    """Return (shifts, problems). Bad rows are skipped and reported, not fatal."""
    shifts: list[Shift] = []
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in headers]
        if missing:
            raise SystemExit(f"Input is missing required columns: {', '.join(missing)}")
        for line_no, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            try:
                if not row["employee"]:
                    raise ValueError("blank employee")
                day = date.fromisoformat(row["date"])
                start = parse_time(day, row["start"])
                end = parse_time(day, row["end"])
                if end <= start:  # overnight shift, e.g. 22:00-06:00
                    end += timedelta(days=1)
                if end - start > timedelta(hours=16):
                    raise ValueError("shift longer than 16 hours")
            except (ValueError, KeyError) as exc:
                problems.append(f"line {line_no}: {exc}")
                continue
            shifts.append(Shift(row["employee"], row["role"], row["location"] or "(none)",
                                start, end))
    return shifts, problems


def hour_slots(shift: Shift):
    """Yield the clock-hour starts in which the shift covers >= PRESENCE_MINUTES."""
    slot = shift.start.replace(minute=0, second=0, microsecond=0)
    while slot < shift.end:
        overlap = min(shift.end, slot + timedelta(hours=1)) - max(shift.start, slot)
        if overlap >= timedelta(minutes=PRESENCE_MINUTES):
            yield slot
        slot += timedelta(hours=1)


def build_coverage(shifts: list[Shift], min_staff: int,
                   open_hour: int | None = None, close_hour: int | None = None):
    """Return rows of (location, date, hour, headcount, names, below_min).

    The operating window per location is the earliest start hour to the latest
    end hour seen that week, unless open_hour/close_hour are given. Every hour
    in the window is reported, so hours with zero staff show up as gaps.
    """
    counts: dict[tuple[str, datetime], list[str]] = defaultdict(list)
    window: dict[str, list[int]] = {}
    days: dict[str, set[date]] = defaultdict(set)
    for s in shifts:
        for slot in hour_slots(s):
            counts[(s.location, slot)].append(s.employee)
            days[s.location].add(slot.date())
        lo = s.start.hour
        hi = s.end.hour + (1 if s.end.minute else 0)
        if s.end.date() > s.start.date():  # overnight: report the full day
            lo, hi = 0, 24
        w = window.setdefault(s.location, [lo, hi])
        w[0], w[1] = min(w[0], lo), max(w[1], hi)

    # Report every calendar day in the roster's range for every location, so a
    # day with nobody scheduled at a location still shows up as a gap.
    first = min(s.start.date() for s in shifts)
    last = max(max(d) for d in days.values())
    all_days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    rows = []
    for loc in sorted(window):
        lo = open_hour if open_hour is not None else window[loc][0]
        hi = close_hour if close_hour is not None else window[loc][1]
        for d in all_days:
            for h in range(lo, hi):
                slot = datetime.combine(d, datetime.min.time()) + timedelta(hours=h)
                names = sorted(counts.get((loc, slot), []))
                rows.append((loc, d, h, len(names), names, len(names) < min_staff))
    return rows


def build_hours(shifts: list[Shift], ot_threshold: float):
    """Return rows of (employee, role, shifts, hours, overtime_hours, flag)."""
    agg: dict[str, dict] = {}
    for s in shifts:
        a = agg.setdefault(s.employee, {"role": s.role, "shifts": 0, "hours": 0.0})
        a["shifts"] += 1
        a["hours"] += s.hours
    rows = []
    for emp, a in sorted(agg.items(), key=lambda kv: (-kv[1]["hours"], kv[0])):
        hrs = round(a["hours"], 2)
        ot = round(max(0.0, hrs - ot_threshold), 2)
        rows.append((emp, a["role"], a["shifts"], hrs, ot, ot > 0))
    return rows


def write_coverage(path: Path, rows) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["location", "date", "weekday", "hour", "headcount", "below_min", "staff"])
        for loc, d, h, n, names, low in rows:
            w.writerow([loc, d.isoformat(), d.strftime("%a"), f"{h:02d}:00", n,
                        "YES" if low else "", "; ".join(names)])


def write_hours(path: Path, rows) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["employee", "role", "shifts", "hours", "overtime_hours", "overtime"])
        for emp, role, n, hrs, ot, flag in rows:
            w.writerow([emp, role, n, f"{hrs:.2f}", f"{ot:.2f}", "YES" if flag else ""])


def _gap_ranges(cov_rows):
    """Collapse consecutive understaffed hours into ranges per location/day."""
    out = []
    current = None
    for loc, d, h, n, _names, low in cov_rows:
        if low and current and current[0] == loc and current[1] == d and current[3] == h:
            current[3] = h + 1
            current[4] = min(current[4], n)
        else:
            if current:
                out.append(tuple(current))
                current = None
            if low:
                current = [loc, d, h, h + 1, n]
    if current:
        out.append(tuple(current))
    return out


def write_summary(path: Path, source: Path, shifts, problems, cov_rows, hour_rows,
                  min_staff: int, ot_threshold: float) -> None:
    low = [r for r in cov_rows if r[5]]
    ot = [r for r in hour_rows if r[5]]
    total_hours = sum(r[3] for r in hour_rows)
    lines = [
        "# Roster Coverage Summary",
        "",
        f"- Source: `{source.name}`",
        f"- Shifts loaded: {len(shifts)} ({len(problems)} row(s) skipped)",
        f"- Employees: {len(hour_rows)}",
        f"- Scheduled hours: {total_hours:.1f}",
        f"- Minimum staff per hour: {min_staff}",
        f"- Understaffed hours: {len(low)} of {len(cov_rows)} operating hours",
        f"- Employees over {ot_threshold:g} h: {len(ot)}",
        "",
        "## Understaffed windows",
        "",
    ]
    gaps = _gap_ranges(cov_rows)
    if gaps:
        lines += ["| Location | Day | Window | Lowest headcount |", "|---|---|---|---|"]
        for loc, d, h0, h1, n in gaps:
            lines.append(f"| {loc} | {d.strftime('%a %Y-%m-%d')} | "
                         f"{h0:02d}:00-{h1:02d}:00 | {n} |")
    else:
        lines.append("None. Every operating hour meets the minimum.")
    lines += ["", "## Overtime", ""]
    if ot:
        lines += ["| Employee | Role | Shifts | Hours | Over by |", "|---|---|---|---|---|"]
        for emp, role, n, hrs, over, _ in ot:
            lines.append(f"| {emp} | {role} | {n} | {hrs:.1f} | {over:.1f} |")
    else:
        lines.append(f"No one is scheduled over {ot_threshold:g} hours.")
    lines += ["", "## Skipped rows", ""]
    lines += [f"- {p}" for p in problems] if problems else ["None."]
    lines.append("")
    path.write_text("\n".join(lines))


def run(input_path: Path, out_dir: Path, min_staff: int = 3, ot_threshold: float = 40.0,
        open_hour: int | None = None, close_hour: int | None = None) -> dict:
    shifts, problems = load_shifts(input_path)
    if not shifts:
        raise SystemExit("No valid shifts found.")
    out_dir.mkdir(parents=True, exist_ok=True)
    cov = build_coverage(shifts, min_staff, open_hour, close_hour)
    hrs = build_hours(shifts, ot_threshold)
    write_coverage(out_dir / "coverage.csv", cov)
    write_hours(out_dir / "hours.csv", hrs)
    write_summary(out_dir / "summary.md", input_path, shifts, problems, cov, hrs,
                  min_staff, ot_threshold)
    return {"shifts": len(shifts), "skipped": len(problems),
            "understaffed_hours": sum(1 for r in cov if r[5]),
            "overtime_employees": sum(1 for r in hrs if r[5])}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Hourly coverage and overtime report for a shift roster CSV.")
    p.add_argument("input", type=Path, help="roster CSV: employee,role,date,start,end,location")
    p.add_argument("--out", type=Path, default=Path("output"), help="output folder (default: output)")
    p.add_argument("--min-staff", type=int, default=3, help="minimum headcount per hour (default: 3)")
    p.add_argument("--ot-threshold", type=float, default=40.0, help="weekly overtime threshold in hours (default: 40)")
    p.add_argument("--open-hour", type=int, help="force the operating window start (0-23)")
    p.add_argument("--close-hour", type=int, help="force the operating window end (1-24)")
    a = p.parse_args(argv)
    stats = run(a.input, a.out, a.min_staff, a.ot_threshold, a.open_hour, a.close_hour)
    print(f"{stats['shifts']} shifts read, {stats['skipped']} skipped | "
          f"{stats['understaffed_hours']} understaffed hours | "
          f"{stats['overtime_employees']} employee(s) over {a.ot_threshold:g} h")
    print(f"Wrote {a.out / 'coverage.csv'}, {a.out / 'hours.csv'}, {a.out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
