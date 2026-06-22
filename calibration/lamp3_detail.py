"""Лампа 3 — SOFR−IORB спред + опашка (p99−p25): база-ставки + епизоди.

Решава: (а) амбер@0bp шумен ли е? (б) да се върже ли опашката в статуса?
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
KEY = os.environ.get("FRED_API_KEY")
UA = {"User-Agent": "calib/0.1", "Accept": "application/json"}


def fred(sid, start):
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(
        {"series_id": sid, "api_key": KEY, "file_type": "json",
         "observation_start": start, "sort_order": "asc"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        doc = json.loads(r.read().decode("utf-8"))
    return {o["date"]: float(o["value"]) for o in doc["observations"]
            if o["value"] not in (".", "", None)}


sofr = fred("SOFR", "2018-04-01")
ioer = fred("IOER", "2018-04-01")
iorb = fred("IORB", "2021-07-29")
p99 = fred("SOFR99", "2018-04-01")
p25 = fred("SOFR25", "2018-04-01")


def policy(d):
    return iorb.get(d, ioer.get(d))


# спред + опашка по дни
spread = {}
tail = {}
for d in sorted(sofr):
    pol = policy(d)
    if pol is not None:
        spread[d] = round((sofr[d] - pol) * 100, 1)
    if d in p99 and d in p25:
        tail[d] = round((p99[d] - p25[d]) * 100, 1)

sv = sorted(spread.values())
tv = sorted(tail.values())


def pct(arr, p):
    return arr[min(len(arr) - 1, int(p / 100 * len(arr)))]


def base_rate(cond):
    return sum(1 for v in spread.values() if cond(v)) / len(spread) * 100


print("=" * 64)
print(f"SOFR−IORB спред (bp), n={len(spread)}  [2018-04 → сега]")
print(f"  p5={pct(sv,5)} p25={pct(sv,25)} p50={pct(sv,50)} p75={pct(sv,75)} "
      f"p90={pct(sv,90)} p95={pct(sv,95)} p99={pct(sv,99)} max={sv[-1]}")
print(f"  база-ставка спред≥0bp (текущ amber): {base_rate(lambda v: v>=0):.1f}%")
print(f"  база-ставка спред≥+2bp:              {base_rate(lambda v: v>=2):.1f}%")
print(f"  база-ставка спред≥+5bp (текущ red):  {base_rate(lambda v: v>=5):.1f}%")
print(f"  база-ставка спред≥+10bp:             {base_rate(lambda v: v>=10):.1f}%")

print("=" * 64)
print(f"Опашка p99−p25 (bp), n={len(tail)}")
print(f"  p50={pct(tv,50)} p90={pct(tv,90)} p95={pct(tv,95)} p99={pct(tv,99)} max={tv[-1]}")

print("=" * 64)
print("Последните 12 месеца — дни със спред≥0 (амбер сега):")
recent = sorted(d for d in spread if d >= "2025-06-01" and spread[d] >= 0)
print(f"  {len(recent)} дни ≥0 от {sum(1 for d in spread if d>='2025-06-01')} (2025-06→)")
for d in recent[-15:]:
    print(f"    {d}: спред {spread[d]:+}bp  опашка {tail.get(d,'—')}bp")

print("=" * 64)
print("Епизоди:")
for d in ("2019-09-17", "2019-09-18", "2025-10-31", "2024-06-14", "2026-06-18"):
    print(f"  {d}: спред {spread.get(d,'—')}bp  опашка {tail.get(d,'—')}bp")
