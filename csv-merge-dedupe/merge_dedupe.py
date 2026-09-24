#!/usr/bin/env python3
"""Merge messy contact CSVs into one clean, de-duplicated file.

What it does
  1. Maps each file's headers onto one schema (exact alias match, then fuzzy
     match with difflib), so "E-mail", "Email Address" and "emial" all land in
     the email column. Unrecognised columns are reported, not guessed.
  2. Normalises values: trims/collapses whitespace, lower-cases emails, formats
     US phone numbers as (NNN) NNN-NNNN, fixes ALL-CAPS / all-lower names and
     cities, and splits "Full Name" or "Last, First" into first/last.
  3. Merges duplicates: rows sharing an email or a phone number are treated as
     one person. The first non-blank value wins; disagreements are logged.
  4. Writes the clean CSV plus a changes log recording every edit.

Standard library only (Python 3.8+).

Usage:
  python3 merge_dedupe.py input/*.csv -o output/merged.csv --log output/changes_log.csv
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from pathlib import Path

SCHEMA = ["first_name", "last_name", "email", "phone", "company", "city"]
ALIASES = {
    "first_name": ["first name", "firstname", "fname", "given name", "first"],
    "last_name": ["last name", "lastname", "lname", "surname", "family name", "last"],
    "full_name": ["full name", "name", "contact name", "contact", "fullname"],
    "email": ["email", "e mail", "email address", "e mail address", "mail"],
    "phone": ["phone", "phone number", "phone no", "mobile", "cell", "telephone", "tel"],
    "company": ["company", "organisation", "organization", "employer", "business",
                "company name", "org"],
    "city": ["city", "town", "locality"],
}
FUZZY_CUTOFF = 0.8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
OUT_FIELDS = SCHEMA + ["sources", "issues"]


# ---------------------------------------------------------------- headers
def norm_header(h: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", h.lower()).split())


_ALIAS_LOOKUP = {a: field for field, names in ALIASES.items() for a in names}


def map_header(header: str) -> tuple[str | None, str]:
    """Return (field or None, how) where how is 'exact', 'fuzzy:<alias>' or 'unmapped'."""
    key = norm_header(header)
    if key in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[key], "exact"
    match = difflib.get_close_matches(key, list(_ALIAS_LOOKUP), n=1, cutoff=FUZZY_CUTOFF)
    if match:
        return _ALIAS_LOOKUP[match[0]], f"fuzzy:{match[0]}"
    return None, "unmapped"


# ----------------------------------------------------------- normalisers
def clean_space(v: str) -> str:
    return " ".join((v or "").split())


def fix_case(v: str) -> str:
    """Title-case values typed in ALL CAPS or all lower; leave mixed case alone."""
    v = clean_space(v)
    if v and (v.isupper() or v.islower()):
        return v.title()
    return v


def norm_email(v: str) -> tuple[str, str | None]:
    v = clean_space(v).lower()
    if v and not EMAIL_RE.match(v):
        return v, f"invalid email '{v}'"
    return v, None


def norm_phone(v: str) -> tuple[str, str | None]:
    raw = clean_space(v)
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return "", None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", None
    return raw, f"invalid phone '{raw}'"


def split_full_name(v: str) -> tuple[str, str]:
    v = clean_space(v)
    if "," in v:  # "Last, First"
        last, first = [p.strip() for p in v.split(",", 1)]
        return first, last
    parts = v.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


# ---------------------------------------------------------------- merging
class Log:
    FIELDS = ["source", "row", "field", "before", "after", "action"]

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, source, row, field, before, after, action):
        self.rows.append({"source": source, "row": row, "field": field,
                          "before": before, "after": after, "action": action})

    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r["action"] == action)


def read_file(path: Path, log: Log) -> list[dict]:
    """Read one CSV and return normalised records in the common schema."""
    records = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        headers = next(reader, [])
        mapping: dict[int, str] = {}
        for i, h in enumerate(headers):
            field, how = map_header(h)
            if field is None:
                log.add(path.name, 1, h, h, "", "column_ignored")
                continue
            if field in mapping.values():
                log.add(path.name, 1, h, h, "", "column_duplicate_ignored")
                continue
            mapping[i] = field
            log.add(path.name, 1, h, h, field, f"header_{how}")

        for row_no, row in enumerate(reader, start=2):
            src = {f: (row[i] if i < len(row) else "") for i, f in mapping.items()}
            if not any(clean_space(v) for v in src.values()):
                log.add(path.name, row_no, "*", "", "", "blank_row_dropped")
                continue
            rec = {f: "" for f in SCHEMA}
            issues = []
            if "full_name" in src and not (src.get("first_name") or src.get("last_name")):
                first, last = split_full_name(src["full_name"])
                src["first_name"], src["last_name"] = first, last
                log.add(path.name, row_no, "full_name", src["full_name"],
                        f"{first} | {last}", "name_split")
            for f in SCHEMA:
                before = src.get(f, "")
                if f == "email":
                    after, problem = norm_email(before)
                elif f == "phone":
                    after, problem = norm_phone(before)
                elif f in ("first_name", "last_name", "city"):
                    after, problem = fix_case(before), None
                else:
                    after, problem = clean_space(before), None
                if problem:
                    issues.append(problem)
                    log.add(path.name, row_no, f, before, after, "flagged_invalid")
                elif after != before and f in src:
                    log.add(path.name, row_no, f, before, after, "normalised")
                rec[f] = after
            rec["_origin"] = f"{path.name}:{row_no}"
            rec["_issues"] = issues
            rec["_email_ok"] = bool(rec["email"]) and not any("email" in i for i in issues)
            rec["_phone_ok"] = bool(rec["phone"]) and not any("phone" in i for i in issues)
            records.append(rec)
    return records


def dedupe(records: list[dict], log: Log) -> list[dict]:
    """Group records that share a valid email or phone (transitively) and merge."""
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[str, int] = {}
    for i, r in enumerate(records):
        keys = []
        if r["_email_ok"]:
            keys.append("e:" + r["email"])
        if r["_phone_ok"]:
            keys.append("p:" + r["phone"])
        for k in keys:
            if k in seen:
                parent[find(i)] = find(seen[k])
            else:
                seen[k] = i

    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(records):
        groups.setdefault(find(i), []).append(r)

    merged = []
    for members in groups.values():
        base = members[0]
        out = {f: base[f] for f in SCHEMA}
        issues = list(base["_issues"])
        for other in members[1:]:
            src, row = other["_origin"].rsplit(":", 1)
            log.add(src, row, "*", "", f"merged into {base['_origin']}", "merged_duplicate")
            for f in SCHEMA:
                if not other[f]:
                    continue
                if not out[f]:
                    out[f] = other[f]
                    log.add(src, row, f, "", other[f], "filled_blank")
                elif other[f].casefold() != out[f].casefold():
                    log.add(src, row, f, other[f], out[f], "conflict_kept_first")
            issues += [i for i in other["_issues"] if i not in issues]
        out["sources"] = "; ".join(m["_origin"] for m in members)
        out["issues"] = "; ".join(issues)
        merged.append(out)
    merged.sort(key=lambda r: (r["last_name"].lower(), r["first_name"].lower(), r["email"]))
    return merged


def run(inputs: list[Path], output: Path, log_path: Path) -> dict:
    log = Log()
    records: list[dict] = []
    for p in inputs:
        records += read_file(p, log)
    merged = dedupe(records, log)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(merged)
    with log_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=Log.FIELDS)
        w.writeheader()
        w.writerows(log.rows)
    return {"files": len(inputs), "rows_in": len(records), "rows_out": len(merged),
            "duplicates_merged": log.count("merged_duplicate"),
            "values_normalised": log.count("normalised"),
            "flagged": log.count("flagged_invalid"),
            "columns_ignored": log.count("column_ignored"),
            "blank_rows": log.count("blank_row_dropped"),
            "conflicts": log.count("conflict_kept_first")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Merge and de-duplicate messy contact CSVs.")
    ap.add_argument("inputs", nargs="+", type=Path, help="CSV files to merge (in priority order)")
    ap.add_argument("-o", "--output", type=Path, default=Path("output/merged.csv"))
    ap.add_argument("--log", type=Path, default=Path("output/changes_log.csv"))
    a = ap.parse_args(argv)
    s = run(a.inputs, a.output, a.log)
    print(f"{s['files']} files, {s['rows_in']} rows in -> {s['rows_out']} unique contacts")
    print(f"  duplicates merged: {s['duplicates_merged']}   values normalised: {s['values_normalised']}")
    print(f"  conflicts logged: {s['conflicts']}   invalid values flagged: {s['flagged']}")
    print(f"  blank rows dropped: {s['blank_rows']}   unrecognised columns: {s['columns_ignored']}")
    print(f"Wrote {a.output} and {a.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
