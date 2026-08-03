#!/usr/bin/env python3
"""Refresh food_price_comparison.csv from product pages.

Reads sources.csv (item -> one or more product URLs), fetches each page,
extracts prices, normalises them to £ per kg (or per litre for liquids), and
rewrites food_price_comparison.csv.

Two kinds of source, chosen per row by whether a `store` is named:

  no store   trolley.co.uk aggregator page -- one page can yield prices for
             several supermarkets at once, read off its retailer logo table.
  store set  any retailer that publishes schema.org Product data, e.g. Ocado.
             The price found is attributed to the named store.

Adding a retailer therefore needs no code change, only a sources.csv row --
provided the site serves its price in the HTML. Tesco, Sainsbury's and ASDA
return 403 to scripted requests and M&S renders prices client-side, so those
cells are left to the routine to fill by hand and are listed in gaps.txt.

Only /product/ pages are requested from trolley.co.uk, which its robots.txt
permits; the disallowed /search/ path is never touched.

Stdlib only, no dependencies.
"""

import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
SOURCES = ROOT / "sources.csv"
OUTPUT = ROOT / "food_price_comparison.csv"
GAPS = ROOT / "gaps.txt"

# Stores worth chasing by hand when trolley has no price. The rest (Aldi,
# Lidl, Iceland, Co-op) barely do online grocery, so they are trolley-only --
# filled when it happens to carry them, never hunted for.
CHASE = {"Ocado", "Sainsbury's", "Tesco", "ASDA", "Morrisons", "Waitrose", "M&S"}

# CSV column order, and the trolley store-logo class that maps to each.
STORES = [
    ("Ocado", "ocado"),
    ("Sainsbury's", "sainsburys"),
    ("Tesco", "tesco"),
    ("ASDA", "asda"),
    ("Morrisons", "morrisons"),
    ("Waitrose", "waitrose"),
    ("Aldi", "aldi"),
    ("Lidl", "lidl"),
    ("Iceland", "iceland"),
    ("Co-op", "coop"),
    ("M&S", "ms"),
]
BY_SLUG = {slug: name for name, slug in STORES}
COLUMNS = [name for name, _ in STORES]

# Marketplaces trolley lists alongside the supermarkets. Not supermarkets.
IGNORED_SLUGS = {"ebay", "amazon"}

# Single-retailer pages have no logo table; the retailer is named in prose
# in the schema.org description instead ("...Offers on X in Waitrose. From...").
BY_PROSE = [
    ("Sainsbury", "Sainsbury's"),
    ("Waitrose", "Waitrose"),
    ("Morrisons", "Morrisons"),
    ("Iceland", "Iceland"),
    ("Ocado", "Ocado"),
    ("Tesco", "Tesco"),
    ("Asda", "ASDA"),
    ("Aldi", "Aldi"),
    ("Lidl", "Lidl"),
    ("Co-op", "Co-op"),
    ("M&S", "M&S"),
]

# Self-identifying, in the conventional "compatible" form. Some retailers
# reject anything without the Mozilla/5.0 prefix outright; this satisfies that
# without pretending to be a browser. Keep it plain -- Ocado's filter rejects
# the string once it carries digits beyond the version.
UA = "Mozilla/5.0 (compatible; food-finder/1.0; personal weekly price comparison)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
DELAY = 1.0


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_size(text):
    """'340g' -> (0.34, 'kg'). '2.272l' -> (2.272, 'l'). '6' -> None."""
    t = text.lower().replace("&nbsp;", " ")
    # Prefer an explicit litre/ml figure (drinks are quoted per litre).
    m = re.search(r"([\d.]+)\s*(l|ml|litre|litres)\b", t)
    if m:
        v = float(m.group(1))
        return (v / 1000 if m.group(2) == "ml" else v), "l"
    m = re.search(r"([\d.]+)\s*(kg|g)\b", t)
    if m:
        v = float(m.group(1))
        return (v if m.group(2) == "kg" else v / 1000), "kg"
    return None


def read_ld_json(page):
    """First schema.org Product block, or {} if the page has none. Trolley
    omits it entirely when it holds no current price for the product."""
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>',
                         page, re.S):
        try:
            doc = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for node in (doc if isinstance(doc, list) else [doc]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return {}


def offer_price(ld):
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price")
    return float(price) if price else None


def scrape_retailer(url, store):
    """A single retailer's own product page. schema.org Product or nothing."""
    ld = read_ld_json(fetch(url))
    name = html.unescape(str(ld.get("name", "")))
    price = offer_price(ld)
    prices = {store: price} if price else {}

    # Ocado puts the pack size in its own field, and repeats it at the head of
    # the description ("Ocado Organic Carrots 750g<br>...") when it does not.
    blurb = html.unescape(re.sub(r"<[^>]+>", " ", str(ld.get("description", ""))))
    parsed = (parse_size(str(ld.get("size", "")))
              or parse_size(name)
              or parse_size(blurb[:120]))
    if parsed is None:
        return name, None, None, prices
    return name, parsed[0], parsed[1], prices


def scrape(url, store):
    """-> (product_name, unit_size, unit, {store: pack_price})"""
    if store:
        return scrape_retailer(url, store)
    return scrape_trolley(url)


def scrape_trolley(url):
    full = fetch(url)
    ld = read_ld_json(full)

    # Everything from here on is 'customers also viewed' -- different products
    # whose prices must not be attributed to this one.
    cut = full.find("store-alternatives")
    page = full[:cut] if cut != -1 else full

    brand = re.search(r'class="_brand">([^<]*)<', page)
    desc = re.search(r'class="_desc">([^<]*)<', page)
    size = re.search(r'class="tag -d-grey-filled[^"]*">([^<]*)<', page)

    name = " ".join(
        html.unescape(m.group(1)).strip() for m in (brand, desc) if m
    ).strip()
    size_text = html.unescape(size.group(1)).strip() if size else ""
    # ld+json spells the size out in the name -- "Duchy Organic Carrots (700g)"
    ld_name = html.unescape(str(ld.get("name", "")))

    prices = {}
    unknown = set()
    for m in re.finditer(r'store-logo -([a-z-]+)"', page):
        slug = m.group(1).replace("-", "")
        window = page[m.end():m.end() + 900]
        pm = re.search(r'class="_price"[^>]*>\s*&pound;?([\d.]+)', window) \
            or re.search(r"&pound;([\d.]+)", window)
        if not pm:
            continue
        price = float(pm.group(1))
        if slug in IGNORED_SLUGS:
            continue
        if slug not in BY_SLUG:
            unknown.add(slug)
            continue
        store = BY_SLUG[slug]
        # A store can appear more than once (e.g. multipack listing); keep the
        # lowest, which is what the comparison is asking for.
        if store not in prices or price < prices[store]:
            prices[store] = price

    for slug in sorted(unknown):
        print(f"  ! unmapped store '{slug}' on {url}", file=sys.stderr)

    # Single-retailer products have no logo table at all. Their one price is
    # the ld+json offer, and the retailer is named in the description.
    if not prices:
        price = offer_price(ld)
        blurb = html.unescape(str(ld.get("description", "")))
        named = re.search(r"Offers on .*? in ([^.]+?)\. From", blurb)
        if price and named:
            for token, store in BY_PROSE:
                if token.lower() in named.group(1).lower():
                    prices[store] = price

    parsed = parse_size(size_text) or parse_size(ld_name) or parse_size(name)
    if parsed is None:
        return (name or ld_name), None, None, prices
    return (name or ld_name), parsed[0], parsed[1], prices


def main():
    rows = list(csv.DictReader(SOURCES.open(encoding="utf-8")))

    items = []          # preserve sources.csv item order
    data = {}           # item -> {store: normalised price}
    failures = []

    for row in rows:
        item = row["item"].strip()
        url = row["url"].strip()
        store = (row.get("store") or "").strip()
        override = (row.get("unit_override") or "").strip()

        if store and store not in COLUMNS:
            failures.append(f"{item}: '{store}' is not a CSV column")
            continue

        if item not in data:
            items.append(item)
            data[item] = {}

        try:
            name, size, unit, prices = scrape(url, store)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            failures.append(f"{item}: FETCH FAILED {url} ({e})")
            continue
        finally:
            time.sleep(DELAY)

        if override:
            parsed = parse_size(override)
            if parsed is None:
                failures.append(f"{item}: bad unit_override '{override}'")
                continue
            size, unit = parsed

        if not prices:
            failures.append(f"{item}: no retailer prices found on {url}")
            continue
        if not size:
            failures.append(
                f"{item}: no pack size for '{name}' ({url}) "
                f"-- set unit_override in sources.csv"
            )
            continue

        for store, pack_price in prices.items():
            per_unit = round(pack_price / size, 2)
            if store not in data[item] or per_unit < data[item][store]:
                data[item][store] = per_unit

        got = ", ".join(f"{s} {p}" for s, p in sorted(prices.items()))
        print(f"  {item:38} {name} ({size}{unit}) -> {got}")

    write_csv(items, data)
    gaps = write_gaps(items, data)

    filled = sum(len(v) for v in data.values())
    print(f"\nWrote {OUTPUT.name}: {len(items)} items, {filled} cells scraped")
    print(f"Wrote {GAPS.name}: {gaps} cells still to find by hand")

    if failures:
        print(f"\n{len(failures)} source(s) yielded nothing:")
        for f in failures:
            print(f"  - {f}")
    return 0


def write_gaps(items, data):
    """The bounded worklist handed to the routine. Never guesses -- an empty
    cell stays empty until something actually finds a price for it."""
    lines = []
    for item in items:
        missing = sorted(CHASE - set(data[item]))
        if missing:
            lines.append(f"{item}: {', '.join(missing)}")
    GAPS.write_text(
        "Cells with no trolley price. Find these on the retailer sites,\n"
        "write them into food_price_comparison.csv normalised per kg (or per\n"
        "litre for drinks), and append any product page you used to\n"
        "sources.csv so it is free next week.\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return sum(len(l.split(":")[1].split(",")) for l in lines)


def write_csv(items, data):
    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["#", "Item"] + COLUMNS + ["Cheapest"])
        for i, item in enumerate(items, 1):
            prices = data[item]
            cells = [f"{prices[c]:.2f}" if c in prices else "" for c in COLUMNS]
            if prices:
                best = min(prices.values())
                cheapest = "/".join(
                    c for c in COLUMNS if prices.get(c) == best
                )
            else:
                cheapest = ""
            w.writerow([i, item] + cells + [cheapest])


if __name__ == "__main__":
    sys.exit(main())
