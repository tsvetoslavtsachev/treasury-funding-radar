"""Лампа 4 — групиране по ОРИГИНАЛЕН тенор (събира reopening-ите) + ширина.

Проверява дали fiscaldata дава original_security_term и преизчислява ширината,
за да се фиксират правилните breadth прагове.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
from funding_radar.common import zscore  # noqa: E402

UA = {"User-Agent": "calib/0.1", "Accept": "application/json"}
BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
EPISODES = [("2019-09-17", "септ-2019"), ("2020-03-18", "март-2020"),
            ("2024-06-14", "СПОКОЕН"), ("2025-10-31", "SRF 31.10.25"), ("2026-06-18", "сега")]
COUPON = {"Note", "Bond"}
ROLL, RECENCY = 10, 45


def fetch():
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({
            "fields": "auction_date,security_type,security_term,original_security_term,"
                      "bid_to_cover_ratio,primary_dealer_accepted,total_accepted",
            "filter": "auction_date:gte:2015-01-01", "sort": "-auction_date",
            "page[size]": 5000, "page[number]": page}, safe=":")
        req = urllib.request.Request(f"{BASE}?{q}", headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            doc = json.loads(r.read().decode("utf-8"))
        data = doc.get("data", [])
        out.extend(data)
        if len(data) < 5000:
            break
        page += 1
    return out


print("Тегля…", file=sys.stderr)
RAW = fetch()
print(f"n={len(RAW)}; полета: {list(RAW[0].keys())}", file=sys.stderr)
print(f"sample original_security_term: {RAW[0].get('original_security_term')!r} "
      f"(security_term={RAW[0].get('security_term')!r})", file=sys.stderr)

rows = []
for d in RAW:
    btc = d.get("bid_to_cover_ratio")
    if btc in (None, "null", ""):
        continue
    pda, tot = d.get("primary_dealer_accepted"), d.get("total_accepted")
    try:
        pd = float(pda) / float(tot) if pda not in (None, "null", "") and tot not in (None, "null", "", "0") else None
    except (ValueError, ZeroDivisionError):
        pd = None
    rows.append({"date": d["auction_date"], "type": d.get("security_type"),
                 "orig": d.get("original_security_term"), "btc": float(btc), "pd": pd})


def breadth(asof):
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=400)).isoformat()
    rec = (dt.date.fromisoformat(asof) - dt.timedelta(days=RECENCY)).isoformat()
    pool = [r for r in rows if r["type"] in COUPON and r["date"] <= asof and r["date"] >= lo]
    by = {}
    for r in pool:
        by.setdefault(r["orig"], []).append(r)
    weak = []
    for tenor, rs in by.items():
        rs.sort(key=lambda x: x["date"], reverse=True)
        latest = rs[0]
        if latest["date"] < rec:
            continue
        hist = [x["btc"] for x in rs[1:1 + ROLL]]
        if len(hist) < 4:
            continue
        z = zscore(latest["btc"], hist, str(len(hist)))["z"]
        if z is not None and z <= -1.5:
            weak.append((tenor, latest["btc"], z, latest["pd"], len(hist)))
    return sorted(weak, key=lambda w: w[2])


for asof, label in EPISODES:
    w = breadth(asof)
    n15 = len(w)
    n20 = sum(1 for x in w if x[2] <= -2)
    print(f"\n{asof} ({label}): слаби купони z≤−1.5: {n15} | z≤−2: {n20}")
    for tenor, btc, z, pd, n in w:
        pds = f"{pd:.0%}" if pd is not None else "—"
        print(f"    {tenor:<10} btc={btc:.2f} z={z:+.2f} (n={n}) PD={pds}")
