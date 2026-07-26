#!/usr/bin/env python3
"""
Refined scan - specifically look for short-term (5-min, 15-min) BTC/ETH price predictions.
Uses strict keyword matching patterns.
"""

import json
import urllib.request
import ssl
import re

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

results = {}


def fetch_json(url, params=None, timeout=20, label=""):
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{qs}"
    else:
        full_url = url
    try:
        req = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PolyScan/1.0)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode())
            print(f"  OK {label}: got data")
            return data
    except Exception as e:
        print(f"  FAIL {label}: {type(e).__name__}: {str(e)[:120]}")
        return None


# Patterns for short-term crypto price predictions
BTC_PAT = re.compile(r"\b(btc|bitcoin)\b", re.I)
ETH_PAT = re.compile(r"\b(eth|ethereum)\b", re.I)
SHORT_TERM_PAT = re.compile(
    r"\b(5\s*min|15\s*min|5min|15min|next\s+(hour|5|15)|hourly|short.?term|intraday|perpetual|perps?)\b",
    re.I,
)
PRICE_PAT = re.compile(
    r"\b(price|above|below|hit|reach|crash|pump|dump|price.?prediction)\b", re.I
)
MIN_PAT = re.compile(r"\b(\d+)\s*min(?:ute)?s?\b", re.I)


def check_refined(obj, source, depth=0):
    """Check market for short-term BTC/ETH prediction patterns."""
    if depth > 2:
        return

    text = json.dumps(obj)
    has_btc = bool(BTC_PAT.search(text))
    has_eth = bool(ETH_PAT.search(text))
    has_price = bool(PRICE_PAT.search(text))
    has_short = bool(SHORT_TERM_PAT.search(text))

    # Find minute patterns
    mins = MIN_PAT.findall(text)

    if (has_btc or has_eth) and (has_price or has_short):
        print(f"\n  *** POTENTIAL MATCH [{source}] ***")
        print(
            f"      BTC={has_btc} ETH={has_eth} PRICE={has_price} SHORT={has_short} MINS={mins}"
        )
        for k in [
            "question",
            "title",
            "slug",
            "tags",
            "description",
            "outcomeType",
            "outcomes",
            "volume",
            "endDate",
        ]:
            if k in obj:
                v = str(obj[k])[:300]
                print(f"      {k}: {v}")

        # Save it
        if source not in results:
            results[source] = []
        entry = {
            "btc": has_btc,
            "eth": has_eth,
            "price": has_price,
            "short": has_short,
            "minutes": mins,
        }
        for k in [
            "question",
            "title",
            "slug",
            "tags",
            "description",
            "outcomeType",
            "outcomes",
            "conditionId",
            "id",
            "volume",
            "endDate",
            "marketSlug",
            "eventSlug",
        ]:
            if k in obj:
                entry[k] = str(obj[k])[:500]
        results[source].append(entry)

    # Check nested markets
    if "markets" in obj and isinstance(obj["markets"], list):
        for m in obj["markets"]:
            check_refined(m, source + "(nested)", depth + 1)


# ====== SCAN ======
print("=" * 70)
print("REFINED SCAN: Short-term BTC/ETH Price Predictions")
print("=" * 70)

# 1. CLOB markets
print("\n-- CLOB markets --")
data = fetch_json(
    "https://clob.polymarket.com/markets", {"limit": "500"}, label="CLOB-p1"
)
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    for m in mlist:
        check_refined(m, "CLOB-p1")
    nc = data.get("nextCursor") if isinstance(data, dict) else None
    if nc:
        data2 = fetch_json(
            "https://clob.polymarket.com/markets",
            {"limit": "500", "nextCursor": nc},
            label="CLOB-p2",
        )
        if data2:
            mlist2 = data2 if isinstance(data2, list) else data2.get("data") or []
            for m in mlist2:
                check_refined(m, "CLOB-p2")

# 2. CLOB sampling
print("\n-- CLOB sampling --")
data = fetch_json("https://clob.polymarket.com/sampling-markets", label="CLOB-sampling")
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    for m in mlist:
        check_refined(m, "CLOB-sampling")

data = fetch_json(
    "https://clob.polymarket.com/sampling-simplified-markets",
    label="CLOB-sampling-simp",
)
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    for m in mlist:
        check_refined(m, "CLOB-sampling-simp")

# 3. Gamma events/markets with specific crypto tags
print("\n-- Gamma events (crypto tags) --")
for tag in ["crypto", "crypto-prices", "price-prediction"]:
    data = fetch_json(
        "https://gamma-api.polymarket.com/events",
        {"limit": "250", "closed": "false", "tagSlug": tag},
        label=f"Gamma-{tag}",
    )
    if data:
        for ev in data:
            check_refined(ev, f"Gamma-{tag}")

print("\n-- Gamma markets (crypto tag) --")
data = fetch_json(
    "https://gamma-api.polymarket.com/markets",
    {"limit": "250", "closed": "false", "tagSlug": "crypto"},
    label="Gamma-mkts-crypto",
)
if data:
    for m in data:
        check_refined(m, "Gamma-mkts-crypto")

# 4. Search by title keywords via Gamma
print("\n-- Gamma events title search --")
for term in [
    "btc price",
    "bitcoin price",
    "eth price",
    "ethereum price",
    "crypto price",
]:
    data = fetch_json(
        "https://gamma-api.polymarket.com/events",
        {"limit": "50", "closed": "false", "titleSearch": term},
        label=f"Gamma-title-{term[:10]}",
    )
    if data:
        print(f"  Found {len(data)} events")
        for ev in data:
            check_refined(ev, f"Gamma-title-{term[:10]}")

# 5. Gamma markets with closed=false, type=updown
print("\n-- Gamma markets updown --")
data = fetch_json(
    "https://gamma-api.polymarket.com/markets",
    {"limit": "250", "closed": "false", "type": "updown"},
    label="Gamma-updown",
)
if data:
    for m in data:
        check_refined(m, "Gamma-updown")

# ====== SUMMARY ======
print("\n" + "=" * 70)
print("REFINED SCAN SUMMARY")
print("=" * 70)

total = sum(len(v) for v in results.values())
print(f"Total potential matches: {total}")

# Print real 5-min/15-min matches
print("\n--- Markets with MINUTE patterns ---")
for source, entries in results.items():
    for e in entries:
        if e.get("minutes"):
            print(f"\n  [{source}] minutes={e['minutes']}")
            print(f"  Question: {e.get('question', '?')}")
            print(f"  Slug: {e.get('slug', '?')}")
            print(
                f"  BTC={e['btc']} ETH={e['eth']} PRICE={e['price']} SHORT={e['short']}"
            )

# Save
with open("/tmp/polysignal-lab/polysignal-lab/refined_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to refined_results.json")
