"""Лампа 4 — base-rate сканиране на кандидат-правила през цялата история.

За всяка седмица 2016→2026 смята купонната ширина (оригинален тенор, recency 45д,
roll 10) и таблира колко често всяко правило би палило → реална false-positive ставка.
Целта: праг, който мълчи в спокойствие, но лови 2019/2020.
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
COUPON = {"Note", "Bond"}
ROLL, RECENCY = 10, 45
# известни стрес прозорци (за да отделим база-ставката в спокойствие)
STRESS = [("2019-09-01", "2019-10-15"), ("2020-03-01", "2020-04-15")]


def fetch():
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({
            "fields": "auction_date,security_type,original_security_term,bid_to_cover_ratio",
            "filter": "auction_date:gte:2014-06-01", "sort": "-auction_date",
            "page[size]": 5000, "page[number]": page}, safe=":")
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}?{q}", headers=UA), timeout=40) as r:
            doc = json.loads(r.read().decode("utf-8"))
        data = doc.get("data", [])
        out.extend(data)
        if len(data) < 5000:
            break
        page += 1
    return out


print("Тегля…", file=sys.stderr)
RAW = fetch()
rows = []
for d in RAW:
    btc = d.get("bid_to_cover_ratio")
    if btc in (None, "null", "") or d.get("security_type") not in COUPON:
        continue
    rows.append({"date": d["auction_date"], "orig": d.get("original_security_term"), "btc": float(btc)})
print(f"купонни редове n={len(rows)}", file=sys.stderr)


def breadth(asof: str):
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=400)).isoformat()
    rec = (dt.date.fromisoformat(asof) - dt.timedelta(days=RECENCY)).isoformat()
    by = {}
    for r in rows:
        if lo <= r["date"] <= asof:
            by.setdefault(r["orig"], []).append(r)
    n15 = n20 = 0
    worst = None
    for tenor, rs in by.items():
        rs.sort(key=lambda x: x["date"], reverse=True)
        if rs[0]["date"] < rec:
            continue
        hist = [x["btc"] for x in rs[1:1 + ROLL]]
        if len(hist) < 4:
            continue
        z = zscore(rs[0]["btc"], hist, str(len(hist)))["z"]
        if z is None:
            continue
        worst = z if worst is None else min(worst, z)
        if z <= -1.5:
            n15 += 1
        if z <= -2:
            n20 += 1
    return n15, n20, worst


def in_stress(d: str) -> bool:
    return any(a <= d <= b for a, b in STRESS)


# седмично сканиране
start = dt.date(2016, 1, 1)
end = dt.date(2026, 6, 18)
d = start
calm = {"R1_any_z2": 0, "R2_2x_z1.5": 0, "R3_2x_z2": 0, "R4_3x_z1.5": 0, "n": 0}
stress_hits = {"R1_any_z2": 0, "R2_2x_z1.5": 0, "R3_2x_z2": 0, "R4_3x_z1.5": 0, "n": 0}
multi_dates = []
while d <= end:
    ds = d.isoformat()
    n15, n20, worst = breadth(ds)
    bucket = stress_hits if in_stress(ds) else calm
    bucket["n"] += 1
    if n20 >= 1:
        bucket["R1_any_z2"] += 1
    if n15 >= 2:
        bucket["R2_2x_z1.5"] += 1
    if n20 >= 2:
        bucket["R3_2x_z2"] += 1
    if n15 >= 3:
        bucket["R4_3x_z1.5"] += 1
    if n15 >= 2 and not in_stress(ds):
        multi_dates.append((ds, n15, n20, round(worst, 2) if worst else None))
    d += dt.timedelta(days=7)

print("\n" + "=" * 70)
print("BASE-RATE на кандидат-правилата (седмично сканиране)")
print("=" * 70)
print(f"{'правило':<14} {'спокойни седмици':>18} {'стрес седмици':>16}")
for k in ("R1_any_z2", "R2_2x_z1.5", "R3_2x_z2", "R4_3x_z1.5"):
    cp = f"{calm[k]}/{calm['n']} ({100*calm[k]/calm['n']:.1f}%)"
    sp = f"{stress_hits[k]}/{stress_hits['n']} ({100*stress_hits[k]/max(stress_hits['n'],1):.0f}%)"
    print(f"{k:<14} {cp:>18} {sp:>16}")
print("\nЛегенда: R1=≥1 купон z≤−2 · R2=≥2 купона z≤−1.5 · R3=≥2 z≤−2 · R4=≥3 z≤−1.5")
print(f"\nСпокойни седмици с ширина ≥2 (z≤−1.5) — кога правило R2 би палило фалшиво ({len(multi_dates)}):")
for ds, n15, n20, w in multi_dates:
    print(f"    {ds}: n15={n15} n20={n20} worst={w}")
