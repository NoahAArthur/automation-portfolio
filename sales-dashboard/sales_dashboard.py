"""Turn a sales CSV into a one-page HTML dashboard and an Excel report with native charts.

    python3 sales_dashboard.py input/sales_2025.csv --out output

Writes:
  output/dashboard.html     one self-contained file (inline SVG charts, no internet needed)
  output/sales_report.xlsx  Summary sheet with 4 native Excel charts, plus the cleaned orders

The HTML part uses only the Python standard library. The Excel part needs openpyxl
(pip install openpyxl); without it, use --no-xlsx.

Expected columns: order_id, order_date (YYYY-MM-DD), region, channel, category,
product, units, unit_price, revenue. Rows that can't be read are skipped and counted,
never silently guessed.
"""
import argparse
import csv
import html
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REQUIRED = ["order_id", "order_date", "region", "channel", "category", "product", "units", "unit_price", "revenue"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Chart colors: the first two slots of a validated colorblind-safe categorical palette
# (checked for light and dark surfaces). A single-series chart always uses slot 1.
LIGHT = {"s1": "#2a78d6", "s2": "#eb6834"}
DARK = {"s1": "#3987e5", "s2": "#d95926"}


# ---------------------------------------------------------------- loading

def load_sales(path):
    """Read the CSV. Returns (rows, skipped) where skipped is a list of (line, reason)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in headers]
        if missing:
            raise ValueError(f"{path}: missing column(s): {', '.join(missing)}")
        reader.fieldnames = headers
        rows, skipped = [], []
        for line, raw in enumerate(reader, start=2):
            rec = {k: (v or "").strip() for k, v in raw.items() if k}
            if not any(rec.values()):
                continue
            try:
                rows.append(_parse_row(rec))
            except ValueError as e:
                skipped.append((line, str(e)))
    return rows, skipped


def _parse_row(rec):
    try:
        d = date.fromisoformat(rec["order_date"])
    except ValueError:
        raise ValueError(f"bad order_date {rec['order_date']!r}")
    for key in ("region", "channel", "category", "product"):
        if not rec[key]:
            raise ValueError(f"blank {key}")
    try:
        units = int(rec["units"])
        price = float(rec["unit_price"].replace("$", "").replace(",", ""))
        revenue = float(rec["revenue"].replace("$", "").replace(",", ""))
    except ValueError:
        raise ValueError("units/unit_price/revenue not a number")
    if units < 0 or revenue < 0:
        raise ValueError("negative units or revenue")
    return {
        "order_id": rec["order_id"], "order_date": d, "region": rec["region"], "channel": rec["channel"],
        "category": rec["category"], "product": rec["product"], "units": units, "unit_price": price,
        "revenue": revenue,
    }


# ---------------------------------------------------------------- summarising

def summarize(rows):
    if not rows:
        raise ValueError("no valid rows to summarise")
    months = sorted({(r["order_date"].year, r["order_date"].month) for r in rows})
    first, last = months[0], months[-1]
    # every month in the range, including any with no sales
    keys, (y, m) = [], first
    while (y, m) <= last:
        keys.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    monthly = defaultdict(float)
    by_channel = defaultdict(lambda: defaultdict(float))
    by_region, by_category, by_product = defaultdict(float), defaultdict(float), defaultdict(float)
    for r in rows:
        k = (r["order_date"].year, r["order_date"].month)
        monthly[k] += r["revenue"]
        by_channel[r["channel"]][k] += r["revenue"]
        by_region[r["region"]] += r["revenue"]
        by_category[r["category"]] += r["revenue"]
        by_product[r["product"]] += r["revenue"]

    total = sum(r["revenue"] for r in rows)
    orders = len({r["order_id"] for r in rows})
    labels = [f"{MONTHS[m - 1]} {y}" if len({y for y, _ in keys}) > 1 else MONTHS[m - 1] for y, m in keys]
    channels = sorted(by_channel, key=lambda c: -sum(by_channel[c].values()))
    ranked = lambda d: sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))  # noqa: E731

    monthly_vals = [round(monthly[k], 2) for k in keys]
    best_i = max(range(len(keys)), key=lambda i: monthly_vals[i])
    last_online = None
    if "Online" in by_channel and monthly_vals[-1]:
        last_online = by_channel["Online"][keys[-1]] / monthly[keys[-1]]
    return {
        "period": f"{MONTHS[first[1] - 1]} {first[0]} to {MONTHS[last[1] - 1]} {last[0]}",
        "kpis": {
            "revenue": round(total, 2),
            "orders": orders,
            "units": sum(r["units"] for r in rows),
            "avg_order": round(total / orders, 2),
            "best_month": labels[best_i],
            "best_month_revenue": monthly_vals[best_i],
            "online_share_last_month": last_online,
        },
        "month_labels": labels,
        "monthly": monthly_vals,
        "channels": {c: [round(by_channel[c][k], 2) for k in keys] for c in channels},
        "regions": [(k, round(v, 2)) for k, v in ranked(by_region)],
        "categories": [(k, round(v, 2)) for k, v in ranked(by_category)],
        "top_products": [(k, round(v, 2)) for k, v in ranked(by_product)[:5]],
    }


# ---------------------------------------------------------------- formatting helpers

def money(v, compact=False):
    if compact:
        for div, suffix in ((1e6, "M"), (1e3, "K")):
            if abs(v) >= div:
                s = f"{v / div:.1f}".rstrip("0").rstrip(".")
                return f"${s}{suffix}"
        return f"${v:,.0f}"
    return f"${v:,.2f}"


def nice_ticks(vmax, count=4):
    """Clean axis ticks from 0 up to at least vmax: 0, 5,000, 10,000 ..."""
    if vmax <= 0:
        return [0, 1]
    raw = vmax / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    ticks, t = [0], 0
    while t < vmax:
        t += step
        ticks.append(round(t, 6))
    return ticks


def text_width(s, size=13):
    """Conservative width estimate for a bold label in a system sans (px)."""
    return math.ceil(len(str(s)) * size * 0.62)


def _e(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- SVG charts

def svg_line_chart(chart_id, labels, series, title, height=260):
    """series: list of (name, values, css_class). One axis only; 2px lines, >=8px end dots."""
    W, H = 560, height
    single = len(series) == 1
    ends = [money(v[-1], True) if single else f"{n} {money(v[-1], True)}" for n, v, _ in series]
    left, top, bottom = 64, 16, 36
    right = 18 + max(text_width(t) for t in ends)  # room for the widest end label, never clipped
    pw, ph = W - left - right, H - top - bottom
    ticks = nice_ticks(max(max(v) for _, v, _ in series))
    ymax = ticks[-1]
    x = lambda i: left + (pw * i / (len(labels) - 1) if len(labels) > 1 else pw / 2)  # noqa: E731
    y = lambda v: top + ph - ph * v / ymax  # noqa: E731
    out = [f'<svg id="{chart_id}" viewBox="0 0 {W} {H}" role="img" aria-label="{_e(title)}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    for t in ticks:
        out.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{_e(money(t, True))}</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    for i, lab in enumerate(labels):
        out.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 14}" text-anchor="middle">{_e(lab)}</text>')
    end_ys = sorted(y(v[-1]) for _, v, _ in series)
    labels_fit = all(b - a >= 16 for a, b in zip(end_ys, end_ys[1:]))  # else legend + tooltip carry it
    for (name, vals, cls), end in zip(series, ends):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        if single:  # a ~10% wash under a lone series
            out.append(f'<polygon class="wash {cls}" points="{x(0):.1f},{top + ph} {pts} {x(len(vals) - 1):.1f},{top + ph}"/>')
        out.append(f'<polyline class="line {cls}" points="{pts}"/>')
        for i, v in enumerate(vals):  # generous invisible hover targets with native tooltips
            out.append(f'<circle class="hit" cx="{x(i):.1f}" cy="{y(v):.1f}" r="12" tabindex="0">'
                       f'<title>{_e(name)}, {_e(labels[i])}: {_e(money(v))}</title></circle>')
        lx, ly = x(len(vals) - 1), y(vals[-1])
        out.append(f'<circle class="dot {cls}" cx="{lx:.1f}" cy="{ly:.1f}" r="4.5"/>')
        if labels_fit:
            out.append(f'<text class="label" x="{lx + 10:.1f}" y="{ly + 4:.1f}">{_e(end)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def svg_bar_chart(chart_id, items, title):
    """Horizontal bars, one series (slot 1), value at the tip, sorted largest first."""
    bar, gap = 22, 14
    W, top = 560, 8
    left = 20 + max(text_width(n) for n, _ in items)
    right = 12 + max(text_width(money(v, True)) for _, v in items)
    H = top + len(items) * (bar + gap) + 8
    pw = W - left - right
    vmax = max(v for _, v in items) or 1
    out = [f'<svg id="{chart_id}" viewBox="0 0 {W} {H}" role="img" aria-label="{_e(title)}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    out.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top - 4}" y2="{H - 4}"/>')
    for i, (name, v) in enumerate(items):
        yy = top + i * (bar + gap)
        w = max(pw * v / vmax, 1)
        r = min(4, w / 2)
        # square at the baseline, 4px rounded at the data end
        path = (f"M{left},{yy} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar - 2 * r} "
                f"a{r},{r} 0 0 1 {-r},{r} h{-(w - r):.1f} z")
        out.append(f'<g tabindex="0"><title>{_e(name)}: {_e(money(v))}</title>'
                   f'<rect class="hit" x="{left}" y="{yy - gap / 2}" width="{pw}" height="{bar + gap}"/>'
                   f'<path class="bar s1" d="{path}"/></g>')
        out.append(f'<text class="cat" x="{left - 10}" y="{yy + bar / 2 + 5}" text-anchor="end">{_e(name)}</text>')
        out.append(f'<text class="label" x="{left + w + 8:.1f}" y="{yy + bar / 2 + 5}">{_e(money(v, True))}</text>')
    out.append("</svg>")
    return "\n".join(out)


def _table(headers, rows):
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<details><summary>Show data table</summary><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>'


# ---------------------------------------------------------------- HTML page

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:%(l1)s;--s2:%(l2)s}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#a3a198;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:%(d1)s;--s2:%(d2)s}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#a3a198;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:%(d1)s;--s2:%(d2)s}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 40px}
header h1{font-size:26px;margin:0 0 4px}
header p{margin:0;color:var(--ink2)}
.kpis{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:14px;margin:22px 0}
.tile,.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.tile .k{color:var(--ink2);font-size:14px}
.tile .v{font-size:30px;font-weight:600;margin-top:4px}
.tile.hero .v{font-size:48px;line-height:1.1}
.tile .d{color:var(--muted);font-size:13px;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card h2{font-size:16px;margin:0 0 2px}
.card .sub{color:var(--ink2);font-size:13px;margin:0 0 8px}
.legend{display:flex;gap:16px;font-size:13px;color:var(--ink2);margin:0 0 4px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
svg{width:100%%;height:auto;display:block;font-family:inherit}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.cat{fill:var(--ink2);font-size:13px}.label{fill:var(--ink);font-size:13px;font-weight:600}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.line.s1{stroke:var(--s1)}.line.s2{stroke:var(--s2)}
.wash.s1{fill:var(--s1);opacity:.10}
.dot{stroke:var(--surface);stroke-width:2}.dot.s1,.bar.s1,.swatch1{fill:var(--s1);background:var(--s1)}
.dot.s2,.swatch2{fill:var(--s2);background:var(--s2)}
.hit{fill:transparent}.hit:focus,g:focus{outline:2px solid var(--s1)}
g:hover .bar{opacity:.85}
details{margin-top:8px;font-size:13px;color:var(--ink2)}
summary{cursor:pointer}
table{border-collapse:collapse;margin-top:6px;width:100%%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:3px 8px;border-bottom:1px solid var(--grid)}
td+td,th+th{text-align:right}
footer{color:var(--muted);font-size:13px;margin-top:22px}
html,body{overflow-x:hidden}.kpis>*,.grid2>*{min-width:0}
@media (max-width:760px){.kpis{grid-template-columns:1fr 1fr}.tile.hero,.tile:last-child{grid-column:1/-1}.grid2{grid-template-columns:1fr}.tile .v{font-size:24px}.tile.hero .v{font-size:40px}}
""" % {"l1": LIGHT["s1"], "l2": LIGHT["s2"], "d1": DARK["s1"], "d2": DARK["s2"]}


def render_html(s, title="Sales dashboard", source_name="", skipped=0):
    k = s["kpis"]
    labels = s["month_labels"]
    tiles = [
        ("hero", "Total revenue", money(k["revenue"]), s["period"]),
        ("", "Orders", f"{k['orders']:,}", f"{k['units']:,} units"),
        ("", "Average order value", money(k["avg_order"]), "revenue ÷ orders"),
        ("", "Best month", k["best_month"], money(k["best_month_revenue"])),
    ]
    tile_html = "".join(
        f'<div class="tile {c}"><div class="k">{_e(a)}</div><div class="v">{_e(b)}</div><div class="d">{_e(d)}</div></div>'
        for c, a, b, d in tiles)

    ch_names = list(s["channels"])[:2]  # two validated colors; more channels would fold into "Other"
    ch_series = [(n, s["channels"][n], f"s{i + 1}") for i, n in enumerate(ch_names)]
    legend = "".join(f'<span><i class="swatch{i + 1}"></i>{_e(n)}</span>' for i, n in enumerate(ch_names))

    cards = [
        ("Monthly revenue", "All channels and regions",
         svg_line_chart("chart-monthly", labels, [("Revenue", s["monthly"], "s1")], "Monthly revenue line chart"),
         _table(["Month", "Revenue"], [(m, money(v)) for m, v in zip(labels, s["monthly"])])),
        ("Revenue by channel", "Monthly revenue per sales channel",
         f'<div class="legend">{legend}</div>'
         + svg_line_chart("chart-channel", labels, ch_series, "Monthly revenue by channel line chart"),
         _table(["Month"] + ch_names, [[m] + [money(s["channels"][n][i]) for n in ch_names] for i, m in enumerate(labels)])),
        ("Revenue by region", "Full period, largest first",
         svg_bar_chart("chart-region", s["regions"], "Revenue by region bar chart"),
         _table(["Region", "Revenue"], [(n, money(v)) for n, v in s["regions"]])),
        ("Revenue by category", "Full period, largest first",
         svg_bar_chart("chart-category", s["categories"], "Revenue by category bar chart"),
         _table(["Category", "Revenue"], [(n, money(v)) for n, v in s["categories"]])),
    ]
    card_html = "".join(
        f'<section class="card"><h2>{_e(h)}</h2><p class="sub">{_e(sub)}</p>{chart}{tbl}</section>'
        for h, sub, chart, tbl in cards)
    note = f"Source: {_e(source_name)}. " if source_name else ""
    if skipped:
        note += f"{skipped} row(s) could not be read and were left out (listed in the console output). "
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><main>
<header><h1>{_e(title)}</h1><p>{_e(s['period'])} · synthetic sample data</p></header>
<div class="kpis">{tile_html}</div>
<div class="grid2">{card_html}</div>
<footer>{note}Hover or tab to a point or bar for its exact value. Each chart has a data table below it.</footer>
</main></body></html>
"""


# ---------------------------------------------------------------- Excel report

def write_xlsx(s, rows, path):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="E8EEF7")
    money_fmt = '"$"#,##0.00'

    ws["A1"] = "Sales summary"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = f"{s['period']} · synthetic sample data"
    k = s["kpis"]
    kpis = [("Total revenue", k["revenue"], money_fmt), ("Orders", k["orders"], "#,##0"),
            ("Units", k["units"], "#,##0"), ("Average order value", k["avg_order"], money_fmt),
            ("Best month", k["best_month"], None)]
    for i, (label, val, fmt) in enumerate(kpis, start=4):
        ws.cell(i, 1, label).font = bold
        c = ws.cell(i, 2, val)
        if fmt:
            c.number_format = fmt

    def header(row, col, names):
        for j, n in enumerate(names):
            c = ws.cell(row, col + j, n)
            c.font, c.fill = bold, head_fill

    # Monthly table (rows 11..), columns A:D
    ch_names = list(s["channels"])
    r0 = 11
    header(r0, 1, ["Month"] + ch_names + ["Total"])
    for i, m in enumerate(s["month_labels"]):
        ws.cell(r0 + 1 + i, 1, m)
        for j, n in enumerate(ch_names):
            ws.cell(r0 + 1 + i, 2 + j, s["channels"][n][i]).number_format = money_fmt
        ws.cell(r0 + 1 + i, 2 + len(ch_names), s["monthly"][i]).number_format = money_fmt
    r_end = r0 + len(s["month_labels"])
    tot_col = 2 + len(ch_names)

    # Region and category tables to the right of the monthly table
    def small_table(row, col, title, items):
        header(row, col, [title, "Revenue"])
        for i, (n, v) in enumerate(items, start=1):
            ws.cell(row + i, col, n)
            ws.cell(row + i, col + 1, v).number_format = money_fmt
        return row + len(items)

    reg_end = small_table(r0, 7, "Region", s["regions"])
    cat_row = reg_end + 3
    cat_end = small_table(cat_row, 7, "Category", s["categories"])
    for col, w in zip("ABCDEFGH", (22, 14, 14, 14, 4, 4, 14, 14)):
        ws.column_dimensions[col].width = w

    palette = [LIGHT["s1"][1:].upper(), LIGHT["s2"][1:].upper()]

    def style_axes(ch, y_title, x_title=None):
        ch.y_axis.title = y_title
        if x_title:
            ch.x_axis.title = x_title
        ch.y_axis.number_format = '"$"#,##0'
        ch.y_axis.majorGridlines = ch.y_axis.majorGridlines  # keep default gridlines
        ch.x_axis.delete = False  # newer Excel hides axes unless this is explicit
        ch.y_axis.delete = False
        ch.width, ch.height = 17, 8.5

    months_ref = Reference(ws, min_col=1, min_row=r0 + 1, max_row=r_end)

    c1 = LineChart()
    c1.title = "Monthly revenue"
    c1.add_data(Reference(ws, min_col=tot_col, min_row=r0, max_row=r_end), titles_from_data=True)
    c1.set_categories(months_ref)
    c1.legend = None
    style_axes(c1, "Revenue (USD)")

    c2 = LineChart()
    c2.title = "Revenue by channel"
    c2.add_data(Reference(ws, min_col=2, max_col=1 + len(ch_names), min_row=r0, max_row=r_end), titles_from_data=True)
    c2.set_categories(months_ref)
    c2.legend.position = "b"
    style_axes(c2, "Revenue (USD)")

    for ch in (c1, c2):
        for i, ser in enumerate(ch.series):
            color = palette[i] if i < len(palette) else "898781"
            ser.graphicalProperties.line.solidFill = color
            ser.graphicalProperties.line.width = 28575  # 2.25 pt
            ser.smooth = False
    c1.series[0].graphicalProperties.line.solidFill = palette[0]

    def bar_chart(title, row, end):
        b = BarChart()
        b.type = "bar"  # horizontal
        b.title = title
        b.add_data(Reference(ws, min_col=8, min_row=row, max_row=end), titles_from_data=True)
        b.set_categories(Reference(ws, min_col=7, min_row=row + 1, max_row=end))
        b.legend = None
        b.x_axis.scaling.orientation = "maxMin"  # largest at the top, like the table
        b.gapWidth = 80
        b.series[0].graphicalProperties.solidFill = palette[0]
        b.series[0].graphicalProperties.line.noFill = True
        style_axes(b, "Revenue (USD)")
        return b

    ws.add_chart(c1, "J2")
    ws.add_chart(c2, "J20")
    ws.add_chart(bar_chart("Revenue by region", r0, reg_end), "U2")
    ws.add_chart(bar_chart("Revenue by category", cat_row, cat_end), "U20")

    # Orders sheet: the cleaned rows as a filterable Excel table
    od = wb.create_sheet("Orders")
    od.append(REQUIRED)
    for r in rows:
        od.append([r["order_id"], r["order_date"], r["region"], r["channel"], r["category"], r["product"],
                   r["units"], r["unit_price"], r["revenue"]])
    for row in od.iter_rows(min_row=2, min_col=2, max_col=2):
        row[0].number_format = "yyyy-mm-dd"
    for col in ("H", "I"):
        for (c,) in od.iter_rows(min_row=2, min_col=ord(col) - 64, max_col=ord(col) - 64):
            c.number_format = money_fmt
    tab = Table(displayName="Orders", ref=f"A1:I{len(rows) + 1}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    od.add_table(tab)
    od.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHI", (11, 12, 9, 10, 11, 20, 7, 11, 11)):
        od.column_dimensions[col].width = w
    ws["A1"].alignment = Alignment(vertical="center")
    wb.save(path)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv", help="sales CSV file")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--title", default="Sales dashboard")
    ap.add_argument("--no-xlsx", action="store_true", help="skip the Excel report (no openpyxl needed)")
    a = ap.parse_args(argv)

    rows, skipped = load_sales(a.csv)
    s = summarize(rows)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "dashboard.html"
    html_path.write_text(render_html(s, a.title, Path(a.csv).name, len(skipped)), encoding="utf-8")
    written = [str(html_path)]
    if not a.no_xlsx:
        xlsx_path = out / "sales_report.xlsx"
        write_xlsx(s, rows, xlsx_path)
        written.append(str(xlsx_path))

    k = s["kpis"]
    print(f"{len(rows)} orders read, {len(skipped)} skipped · {s['period']}")
    print(f"  revenue {money(k['revenue'])} · avg order {money(k['avg_order'])} · best month {k['best_month']}")
    for line, reason in skipped:
        print(f"  skipped line {line}: {reason}", file=sys.stderr)
    print("Wrote " + " and ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
