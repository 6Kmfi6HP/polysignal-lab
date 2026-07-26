#!/usr/bin/env python3
"""
Polymarket BTC/ETH 5-min & 15-min Price Prediction Market Scanner
Scans CLOB API, Gamma API, and Data API endpoints for relevant markets.
"""

import json
import urllib.request
import urllib.error
import ssl
import sys
import time

BTC_KEYWORDS = ["btc", "bitcoin", "BTC", "Bitcoin"]
ETH_KEYWORDS = ["eth", "ethereum", "ETH", "Ethereum"]
TIME_KEYWORDS = [
    "5 min",
    "15 min",
    "5 minute",
    "15 minute",
    "5min",
    "15min",
    "short",
    "Short",
]

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

results = {"clob": [], "gamma": [], "data_api": [], "errors": []}


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
            sz = (
                len(data)
                if isinstance(data, list)
                else (len(data.keys()) if isinstance(data, dict) else "?")
            )
            print(f"  OK {label}: [{sz}]")
            return data
    except Exception as e:
        err = f"  FAIL {label}: {type(e).__name__}: {str(e)[:150]}"
        print(err)
        results["errors"].append(err)
        return None


def check(obj, source):
    """Check a market/event dict for BTC/ETH/time keywords."""

    def has_kw(kwlist):
        s = json.dumps(obj).lower()
        return any(k.lower() in s for k in kwlist)

    has_btc = has_kw(BTC_KEYWORDS)
    has_eth = has_kw(ETH_KEYWORDS)
    has_time = has_kw(TIME_KEYWORDS)

    if has_btc or has_eth:
        entry = {
            "source": source,
            "btc": has_btc,
            "eth": has_eth,
            "time": has_time,
            "fields": {},
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
            "volumeNum",
            "startDate",
            "endDate",
            "marketSlug",
            "eventSlug",
            "category",
            "seriesSlug",
        ]:
            if k in obj:
                entry["fields"][k] = obj[k]
        cat = (
            "clob"
            if "CLOB" in source
            else ("gamma" if "Gamma" in source else "data_api")
        )
        results[cat].append(entry)
        q = entry["fields"].get("question") or entry["fields"].get("title") or "?"
        s = entry["fields"].get("slug") or entry["fields"].get("marketSlug") or "?"
        print(
            f"    >> {source}: q='{q}' slug='{s}' btc={has_btc} eth={has_eth} time={has_time}"
        )
        return True
    return False


def check_list(lst, source, max_check=500):
    if not lst:
        return
    for item in lst if isinstance(lst, list) else []:
        check(item, source)
        if "markets" in item and isinstance(item["markets"], list):
            for m in item["markets"]:
                check(m, source + "(nested)")


# ====== 0. USE MCP TOOLS FIRST ======
print("=" * 70)
print("PHASE 0: MCP TOOL-BASED SEARCH (PolyWin)")
print("=" * 70)
# We'll run the MCP tools via the agent; this script focuses on raw HTTP

# ====== 1. CLOB API ======
print("\n" + "=" * 70)
print("PHASE 1: CLOB API")
print("=" * 70)

# 1a
print("\n-- 1a. CLOB markets limit=500 --")
data = fetch_json(
    "https://clob.polymarket.com/markets", {"limit": "500"}, label="CLOB/p1"
)
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    print(f"  Count: {len(mlist)}")
    check_list(mlist, "CLOB-mkts-p1")
    # Try page 2
    nc = data.get("nextCursor") if isinstance(data, dict) else None
    if nc:
        print(f"  Fetching page 2...")
        data2 = fetch_json(
            "https://clob.polymarket.com/markets",
            {"limit": "500", "nextCursor": nc},
            label="CLOB/p2",
        )
        if data2:
            mlist2 = data2 if isinstance(data2, list) else data2.get("data") or []
            print(f"  P2 Count: {len(mlist2)}")
            check_list(mlist2, "CLOB-mkts-p2")

# 1b
print("\n-- 1b. CLOB sampling-markets --")
data = fetch_json("https://clob.polymarket.com/sampling-markets", label="CLOB-sampling")
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    print(f"  Count: {len(mlist)}")
    check_list(mlist, "CLOB-sampling")

# 1c
print("\n-- 1c. CLOB sampling-simplified-markets --")
data = fetch_json(
    "https://clob.polymarket.com/sampling-simplified-markets",
    label="CLOB-sampling-simp",
)
if data:
    mlist = data if isinstance(data, list) else data.get("data") or []
    print(f"  Count: {len(mlist)}")
    check_list(mlist, "CLOB-sampling-simp")

# 1d - midpoints to see active tokens
print("\n-- 1d. CLOB midpoints --")
data = fetch_json("https://clob.polymarket.com/midpoints", label="CLOB-midpoints")
if data:
    print(f"  Active token count: {len(data)}")

# ====== 2. GAMMA API ======
print("\n" + "=" * 70)
print("PHASE 2: GAMMA API")
print("=" * 70)

# 2a
print("\n-- 2a. Gamma events tag=crypto --")
data = fetch_json(
    "https://gamma-api.polymarket.com/events",
    {"limit": "250", "closed": "false", "tag": "crypto"},
    label="Gamma-ev-crypto",
)
if data:
    print(f"  Count: {len(data)}")
    check_list(data, "Gamma-ev-crypto")

# 2b
print("\n-- 2b. Gamma events tagSlug=crypto --")
data = fetch_json(
    "https://gamma-api.polymarket.com/events",
    {"limit": "250", "closed": "false", "tagSlug": "crypto"},
    label="Gamma-ev-tagSlug",
)
if data:
    print(f"  Count: {len(data)}")
    check_list(data, "Gamma-ev-tagSlug")

# 2c
print("\n-- 2c. Gamma markets tag=crypto type=updown --")
data = fetch_json(
    "https://gamma-api.polymarket.com/markets",
    {"limit": "250", "closed": "false", "tag": "crypto", "type": "updown"},
    label="Gamma-mkt-updown",
)
if data:
    print(f"  Count: {len(data)}")
    check_list(data, "Gamma-mkt-updown")

# 2d
print("\n-- 2d. Gamma series --")
data = fetch_json("https://gamma-api.polymarket.com/series", label="Gamma-series")
if data:
    print(f"  Count: {len(data)}")
    for s in data:
        check(s, "Gamma-series")

# 2e
print("\n-- 2e. Gamma tags --")
data = fetch_json("https://gamma-api.polymarket.com/tags", label="Gamma-tags")
if data:
    print(f"  Count: {len(data)}")
    for t in data:
        check(t, "Gamma-tags")
    # Print all tags for reference
    print("\n  All tags:")
    for t in data:
        lbl = t.get("label") or t.get("name") or t.get("slug") or "?"
        slug = t.get("slug") or "?"
        print(f"    - {lbl} (slug={slug})")

# 2f - more tag variations
print("\n-- 2f. Gamma events with various tagSlugs --")
for ts in ["price-prediction", "bitcoin", "ethereum", "trading", "defi", "volatility"]:
    data = fetch_json(
        "https://gamma-api.polymarket.com/events",
        {"limit": "100", "closed": "false", "tagSlug": ts},
        label=f"Gamma-ev-{ts}",
    )
    if data:
        print(f"  Count: {len(data)}")
        check_list(data, f"Gamma-ev-{ts}")

# 2g - markets without type filter
print("\n-- 2g. Gamma markets broad search --")
data = fetch_json(
    "https://gamma-api.polymarket.com/markets",
    {"limit": "250", "closed": "false"},
    label="Gamma-mkt-all",
)
if data:
    print(f"  Count: {len(data)}")
    check_list(data, "Gamma-mkt-all")

# 2h
print("\n-- 2h. Gamma markets tagSlug=crypto --")
data = fetch_json(
    "https://gamma-api.polymarket.com/markets",
    {"limit": "250", "closed": "false", "tagSlug": "crypto"},
    label="Gamma-mkt-tagSlug",
)
if data:
    print(f"  Count: {len(data)}")
    check_list(data, "Gamma-mkt-tagSlug")

# ====== 3. DATA API ======
print("\n" + "=" * 70)
print("PHASE 3: DATA API")
print("=" * 70)

# 3a
print("\n-- 3a. causal-data.exchange --")
data = fetch_json(
    "https://causal-data.exchange/polymarket/v1/markets", label="causal-data"
)
if data:
    if isinstance(data, list):
        check_list(data, "causal-data")
    elif isinstance(data, dict):
        for k in ["data", "results", "markets"]:
            if k in data and isinstance(data[k], list):
                check_list(data[k], "causal-data")
                break

# 3b
print("\n-- 3b. data.polymarket.com variants --")
for ep in [
    "https://data.polymarket.com/v1/markets",
    "https://data.polymarket.com/markets",
    "https://data.polymarket.com/api/markets",
    "https://data.polymarket.com/v1/events",
    "https://data.polymarket.com/events",
    "https://data.polymarket.com/v1/tokens",
    "https://data.polymarket.com/tokens",
    "https://data.polymarket.com/v1/prices",
]:
    data = fetch_json(ep, label=f"data-pm")
    if data:
        if isinstance(data, list):
            check_list(data, "data-pm")
        elif isinstance(data, dict):
            for ck in ["data", "results", "markets", "events"]:
                if ck in data and isinstance(data[ck], list):
                    check_list(data[ck], "data-pm")
                    break

# 3c
print("\n-- 3c. data.polymarket.com with params --")
for params in [
    {"limit": "100"},
    {"limit": "50", "type": "crypto"},
    {"limit": "50", "category": "crypto"},
]:
    data = fetch_json(
        "https://data.polymarket.com/markets", params, label=f"data-pm-params"
    )
    if data:
        if isinstance(data, list):
            check_list(data, "data-pm-params")
        elif isinstance(data, dict):
            for ck in ["data", "results", "markets"]:
                if ck in data and isinstance(data[ck], list):
                    check_list(data[ck], "data-pm-params")
                    break

# ====== SUMMARY ======
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
total = sum(len(v) for k, v in results.items() if k != "errors")
print(f"Total matches: {total}")
print(f"  CLOB: {len(results['clob'])}")
print(f"  Gamma: {len(results['gamma'])}")
print(f"  Data API: {len(results['data_api'])}")
print(f"  Errors: {len(results['errors'])}")

# Time-relevant
time_matches = [
    m for m in results["clob"] + results["gamma"] + results["data_api"] if m.get("time")
]
print(f"\n⏱ Time-relevant (5min/15min/short): {len(time_matches)}")
for m in time_matches:
    print(f"  [{m['source']}] btc={m['btc']} eth={m['eth']}")
    print(f"    fields={json.dumps(m['fields'], indent=2)[:400]}")

# Save
with open("/tmp/polysignal-lab/polysignal-lab/scan_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nSaved to scan_results.json")
