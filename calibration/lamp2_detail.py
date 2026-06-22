"""Лампа 2 deep-dive — SRF/repo праг + quarter-end сезонност + ON RRP история.

Гради се: SRF (RPONTSYD) трябва да светне на 31.10.2025 ($29.4млрд) без да пали на
рутинните quarter-end blip-ове. Плюс: структурно ли е ON RRP≈0 сега (→ преработи правилото)?
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


def fred(series_id, start, end=None):
    p = {"series_id": series_id, "api_key": KEY, "file_type": "json",
         "observation_start": start, "sort_order": "asc"}
    if end:
        p["observation_end"] = end
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(p)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        doc = json.loads(r.read().decode("utf-8"))
    return [(o["date"], float(o["value"])) for o in doc["observations"]
            if o["value"] not in (".", "", None)]


def is_qe(d: str) -> bool:
    """Quarter-end прозорец: последните дни на мар/юни/сеп/дек."""
    m, day = int(d[5:7]), int(d[8:10])
    return (m in (3, 6, 9, 12) and day >= 27) or (m in (4, 7, 10, 1) and day <= 3)


print("=" * 72)
print("A) RPONTSYD (SRF/repo take-up) — откакто SRF съществува (2021-07)")
rp = fred("RPONTSYD", "2021-07-28")
nonzero = [(d, v) for d, v in rp if v >= 1.0]
print(f"  дни общо: {len(rp)} | дни с usage ≥$1млрд: {len(nonzero)}")
vals = sorted(v for _, v in rp)
import statistics  # noqa: E402
def pct(p): return vals[min(len(vals) - 1, int(p / 100 * len(vals)))]
print(f"  персентили (всички дни): p50={pct(50):.2f} p90={pct(90):.2f} "
      f"p95={pct(95):.2f} p99={pct(99):.2f} max={vals[-1]:.1f}")
print("  Всички дни с usage ≥$5млрд (QE=quarter-end?):")
for d, v in rp:
    if v >= 5.0:
        print(f"    {d}: {v:>7.2f}  {'[QE]' if is_qe(d) else '[НЕ-QE]'}")

print("=" * 72)
print("B) ON RRP (RRPONTSYD) — структурно ли е ≈0 сега?")
rrp = fred("RRPONTSYD", "2023-01-01")
# тримесечни снимки
seen = set()
for d, v in rrp:
    ym = d[:7]
    if ym[5:] in ("01", "04", "07", "10") and ym not in seen:
        seen.add(ym)
        print(f"    {d}: ON RRP = ${v:,.1f}млрд")

print("=" * 72)
print("C) WRESBAL резерви — траектория спрямо пода 2.8/3.0трлн")
res = fred("WRESBAL", "2024-01-01")
for d, v in res[::8]:   # ~на 8 седмици
    tn = v / 1e6
    band = "🟢" if tn >= 3.0 else ("🟡" if tn >= 2.8 else "🔴")
    print(f"    {d}: {tn:.3f}трлн {band}")
print(f"    последно: {res[-1][0]}: {res[-1][1]/1e6:.3f}трлн")
