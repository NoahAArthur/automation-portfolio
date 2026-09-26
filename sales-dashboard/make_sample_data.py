"""Generate the synthetic sales CSV used by this sample.

Everything here is made up: a fictional store selling four product
categories through two channels in four regions during 2025. A fixed
random seed means the file is the same every time it is generated.

    python3 make_sample_data.py input/sales_2025.csv
"""
import csv
import random
import sys
from datetime import date, timedelta

REGIONS = {"North": 1.00, "South": 0.80, "East": 1.25, "West": 0.65}
CHANNELS = {"Online": 0.55, "In-store": 0.45}
PRODUCTS = [
    # (category, product, unit price)
    ("Coffee", "House Blend 1 lb", 14.00),
    ("Coffee", "Single Origin 12 oz", 18.50),
    ("Tea", "Green Tea Tin", 11.00),
    ("Tea", "Chai Concentrate", 9.50),
    ("Equipment", "Pour-Over Kit", 42.00),
    ("Equipment", "Burr Grinder", 89.00),
    ("Merch", "Logo Mug", 12.00),
    ("Merch", "Tote Bag", 16.00),
]
# Seasonal demand: a slow start, a summer dip, and a strong Q4.
SEASON = [0.85, 0.80, 0.95, 1.00, 1.05, 0.90, 0.85, 0.90, 1.05, 1.15, 1.35, 1.60]
FIELDS = ["order_id", "order_date", "region", "channel", "category", "product", "units", "unit_price", "revenue"]


def generate(seed=2025):
    rng = random.Random(seed)
    rows = []
    day = date(2025, 1, 1)
    n = 1
    while day.year == 2025:
        # Online grows through the year; in-store stays flat.
        online_share = 0.40 + 0.25 * (day.month - 1) / 11
        orders_today = max(1, round(rng.gauss(4.5 * SEASON[day.month - 1], 1.2)))
        for _ in range(orders_today):
            region = rng.choices(list(REGIONS), weights=list(REGIONS.values()))[0]
            channel = "Online" if rng.random() < online_share else "In-store"
            category, product, price = rng.choice(PRODUCTS)
            units = rng.choices([1, 2, 3, 4, 6], weights=[50, 25, 12, 8, 5])[0]
            rows.append({
                "order_id": f"SO-{n:05d}",
                "order_date": day.isoformat(),
                "region": region,
                "channel": channel,
                "category": category,
                "product": product,
                "units": units,
                "unit_price": f"{price:.2f}",
                "revenue": f"{units * price:.2f}",
            })
            n += 1
        day += timedelta(days=1)
    return rows


def main(path):
    rows = generate()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} synthetic orders to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "input/sales_2025.csv")
