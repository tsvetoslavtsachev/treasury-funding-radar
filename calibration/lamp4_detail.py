"""Лампа 4 deep-dive — защо е trigger-happy + дизайн на калибрирания тригер.

Показва per-тенор bid-to-cover z (rolling прозорец) за купони vs бонове при всеки
епизод, за да се види ширината (breadth) и да се проектира праг емпирично.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from funding_radar import sources as S          # noqa: E402
from funding_radar.common import zscore          # noqa: E402

EPISODES = [
    ("2019-09-17", "септ-2019"), ("2020-03-18", "март-2020"),
    ("2024-06-14", "СПОКОЕН"), ("2025-10-31", "SRF 31.10.25"),
    ("2026-06-18", "сега"),
]
COUPON = {"Note", "Bond"}          # купони = истинският demand сигнал
ROLL = 10                          # rolling прозорец: последни N същотенорни аукциона

print("Тегля аукциони…", file=sys.stderr)
A = S.fetch_auctions(base="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
                     path="/v1/accounting/od/auctions_query", since="2015-01-01", page_size=10000)
print(f"n={len(A)}", file=sys.stderr)


def per_tenor_z(asof: str, types: set[str]):
    """Връща {term: (latest_btc, z, n, pd_share, latest_date)} за дадените типове."""
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=400)).isoformat()
    pool = [a for a in A if a["security_type"] in types and a["auction_date"] <= asof]  # desc
    by_term: dict[str, list[dict]] = {}
    for a in pool:
        by_term.setdefault(a["term"], []).append(a)
    out = {}
    for term, rows in by_term.items():
        latest = rows[0]
        if latest["auction_date"] < lo:          # няма скорошен аукцион в прозореца
            continue
        hist = [r["bid_to_cover"] for r in rows[1:1 + ROLL]]
        if len(hist) < 4:
            continue
        z = zscore(latest["bid_to_cover"], hist, f"{len(hist)}")["z"]
        out[term] = (latest["bid_to_cover"], z, len(hist), latest["primary_dealer_share"],
                     latest["auction_date"])
    return out


for asof, label in EPISODES:
    print("\n" + "=" * 96)
    print(f"AS-OF {asof}  ({label})")
    print("-" * 96)
    cp = per_tenor_z(asof, COUPON)
    print("КУПОНИ (Note/Bond):")
    weak15 = weak20 = 0
    for term in sorted(cp, key=lambda t: cp[t][1]):
        btc, z, n, pd, d = cp[term]
        flag = "🔴" if z is not None and z <= -2 else ("🟡" if z is not None and z <= -1.5 else "  ")
        if z is not None and z <= -1.5:
            weak15 += 1
        if z is not None and z <= -2:
            weak20 += 1
        pds = f"{pd:.1%}" if pd is not None else "—"
        print(f"  {flag} {term:<10} btc={btc:.2f}  z={z:+.2f} (n={n})  PDдял={pds}  [{d}]")
    print(f"  → ширина: тенори с z≤−1.5: {weak15} | z≤−2: {weak20}  (от {len(cp)} активни)")
    bills = per_tenor_z(asof, {"Bill"})
    bw = sum(1 for t in bills if bills[t][1] is not None and bills[t][1] <= -2)
    print(f"БОНОВЕ (Bill): {len(bills)} активни, z≤−2: {bw}  "
          f"(шумни — текущата логика пали тук)")
