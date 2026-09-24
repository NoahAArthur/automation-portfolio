# CSV Merge and De-duplicate

A Python command-line tool that takes several messy contact exports and combines them into one clean list. It also writes a log of every change it made.

It handles problems that are common in real exports:

- **Different header spellings.** `Email Address`, `E-mail`, `emial` (typo) and so on are matched to a standard column. Exact aliases are tried first, then a fuzzy match using `difflib`. Columns it can't recognise are reported instead of guessed.
- **Messy values.** It trims extra whitespace, lower-cases emails, puts US phone numbers in `(NNN) NNN-NNNN` format, fixes `ALL CAPS` and `all lower` names and cities, and splits `Full Name` or `Last, First` into two columns.
- **Duplicate people.** Rows that share an email or phone number are merged, including chains where A matches B by email and B matches C by phone. The first non-blank value wins, blank fields are filled from later rows, and conflicts are logged.
- **Invalid data.** Bad emails and phone numbers are kept but flagged in an `issues` column. Blank rows are dropped.

It uses only the Python 3 standard library.

## Usage

```bash
python3 merge_dedupe.py input/crm_export.csv input/event_signups.csv input/newsletter_list.csv \
    -o output/merged.csv --log output/changes_log.csv
```

```
3 files, 21 rows in -> 13 unique contacts
  duplicates merged: 8   values normalised: 26
  conflicts logged: 2   invalid values flagged: 2
  blank rows dropped: 1   unrecognised columns: 1
Wrote output/merged.csv and output/changes_log.csv
```

List the input files in priority order. When two files disagree on a value, the earlier file wins.

## Sample

The same person in two inputs:

```
crm_export.csv        marcus ,OYELARAN,Marcus.Oyelaran@Example.com,555.010.1002,Brightline Supply,Tacoma
event_signups.csv    Marcus Oyelaran,marcus.oyelaran@example.com,,Brightline Supply,Tacoma
```

Becomes one row in `output/merged.csv`:

```
first_name,last_name,email,phone,company,city,sources,issues
Marcus,Oyelaran,marcus.oyelaran@example.com,(555) 010-1002,Brightline Supply,Tacoma,crm_export.csv:3; event_signups.csv:3,
```

`output/changes_log.csv` records every edit:

```
source,row,field,before,after,action
newsletter_list.csv,1,emial,emial,email,header_fuzzy:email
newsletter_list.csv,1,Signup Source,Signup Source,,column_ignored
crm_export.csv,3,last_name,OYELARAN,Oyelaran,normalised
event_signups.csv,2,company,Harbor Tools Inc,Harbor Tools,conflict_kept_first
newsletter_list.csv,3,phone,,(555) 010-1006,filled_blank
event_signups.csv,6,email,kofi.mensah@example,kofi.mensah@example,flagged_invalid
```

## Limits

- Duplicates are matched only on email and phone, not on name alone, because two different people can share a name.
- Phone formatting assumes US or Canada numbers with 10 digits, or 11 with a leading 1. Other numbers are kept as entered and flagged.
- To change the output columns or add header aliases, edit `SCHEMA` and `ALIASES` at the top of the script.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The seven tests cover header mapping (exact, fuzzy, and rejection of unrelated columns), phone, email and name normalisation, chained merges, and a full run on the three sample files.

## Data

All three input files are synthetic. Emails use the reserved `example.com`, `example.org` and `example.net` domains, and phone numbers use the fictional 555-01xx range.
