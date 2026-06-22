"""Source-resolution проба за бектест калибрацията (gate 3).

НЕ production. Резолвва кои исторически серии са достъпни за калибрационните
епизоди (септ 2019 + 31.10.2025), за да се проектира бектест харнесът.

Run: FRED_API_KEY=... python calibration/probe.py
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
if not KEY:
    sys.exit("FRED_API_KEY липсва")

UA = {"User-Agent": "treasury-funding-radar-calib/0.1", "Accept": "application/json"}


def get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fred(series_id: str, start: str, end: str):
    q = urllib.parse.urlencode({
        "series_id": series_id, "api_key": KEY, "file_type": "json",
        "observation_start": start, "observation_end": end, "sort_order": "asc",
    })
    try:
        doc = get(f"https://api.stlouisfed.org/fred/series/observations?{q}")
        obs = [(o["date"], o["value"]) for o in doc.get("observations", [])
               if o["value"] not in (".", "", None)]
        return obs
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


def fred_exists(series_id: str):
    q = urllib.parse.urlencode({"series_id": series_id, "api_key": KEY, "file_type": "json"})
    try:
        doc = get(f"https://api.stlouisfed.org/fred/series?{q}")
        s = doc["seriess"][0]
        return f"OK '{s['title'][:60]}' [{s['observation_start']}..{s['observation_end']}] {s['frequency_short']}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


print("=" * 70)
print("A) FRED IOER (IORB страна за септ 2019; IORB не съществува тогава)")
print("  IOER exists:", fred_exists("IOER"))
print("  IORB exists:", fred_exists("IORB"))
print("  IOER септ 2019:", fred("IOER", "2019-09-10", "2019-09-20"))

print("=" * 70)
print("B) FRED SOFR пик септ 2019")
print("  SOFR exists:", fred_exists("SOFR"))
print("  SOFR 2019-09-13..20:", fred("SOFR", "2019-09-13", "2019-09-20"))

print("=" * 70)
print("C) FRED SOFR персентилни серии (за tail p99-p25)")
for sid in ("SOFR1", "SOFR25", "SOFR75", "SOFR99"):
    print(f"  {sid}:", fred_exists(sid))
print("  SOFR99 септ 2019:", fred("SOFR99", "2019-09-13", "2019-09-20"))

print("=" * 70)
print("D) FRED repo операции (SRF/temporary OMO take-up — за 31.10.2025 $29.4bn)")
for sid in ("RPONTSYD", "RPONTTLD", "WORAL"):
    print(f"  {sid}:", fred_exists(sid))
print("  RPONTSYD 2025-10-27..11-03:", fred("RPONTSYD", "2025-10-27", "2025-11-03"))

print("=" * 70)
print("E) WRESBAL резерви — септ 2019 ниво (режимна проверка на пода)")
print("  WRESBAL септ 2019:", fred("WRESBAL", "2019-09-01", "2019-09-30"))

print("=" * 70)
print("F) NY Fed SOFR history endpoint (персентили за 2019?)")
try:
    doc = get("https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
              "?startDate=2019-09-13&endDate=2019-09-18")
    rr = doc.get("refRates", [])
    print(f"  refRates n={len(rr)}; sample:", json.dumps(rr[0], indent=0) if rr else "празно")
except Exception as e:
    print(f"  ERR {type(e).__name__}: {e}")
