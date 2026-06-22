"""Лампа 4 PD-дял ос (v1.1) — point-in-time валидация + база-ставка скан. No-auth.

Доказва: (1) известните слаби аукциони палят (фев-2021 7Y, ноем-2023 30Y);
(2) спокойно остава зелено; (3) новият PD-amber път НЕ е шумен (нисък base rate).
Тегли TreasuryDirect аукционите веднъж, реже point-in-time (trailing 400д като
production), пуска СЪЩАТА lamp4_auctions логика.

Run: python calibration/lamp4_pd_detail.py   (no key)
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

from funding_radar import lamps as L          # noqa: E402
from funding_radar import sources as S         # noqa: E402

A = S.fetch_auctions(base="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
                     path="/v1/accounting/od/auctions_query", since="2014-06-01", page_size=10000)
print(f"аукциони: n={len(A)}  {A[-1]['auction_date']} … {A[0]['auction_date']}", file=sys.stderr)


def asof(d: str) -> list[dict]:
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=400)).isoformat()
    return [a for a in A if lo <= a["auction_date"] <= d]


GLYPH = {"green": "🟢", "amber": "🟡", "red": "🔴", "null": "⚪"}
EPISODES = [
    ("2021-02-25", "Фев-2021 7Y провал (легендарен)"),
    ("2023-11-09", "Ноем-2023 30Y слаб"),
    ("2024-01-17", "Яну-2024 20Y (PD>btc подценява)"),
    ("2018-10-24", "Окт-2018 (купувачка стачка)"),
    ("2024-06-14", "СПОКОЕН контрол"),
    ("2026-06-22", "Сега"),
]
print("\n" + "=" * 100)
print("ЛАМПА 4 PD-дял (v1.1) — епизоди, point-in-time")
print("=" * 100)
hdr = f"{'as-of':<12} {'епизод':<34} {'статус':<7} {'btc_z':>7} {'n_w15':>5} {'n_w20':>5} {'n_pd':>5} {'pd_amber':>8}"
print(hdr); print("-" * len(hdr))
for d, label in EPISODES:
    lamp = L.lamp4_auctions(asof(d))
    det = lamp.get("detail", {})
    det = det if isinstance(det, dict) else {}
    print(f"{d:<12} {label:<34} {GLYPH[lamp['status']]:<6} "
          f"{str(det.get('worst_bid_to_cover_z','—')):>7} {det.get('n_weak_z15','—')!s:>5} "
          f"{det.get('n_weak_z20','—')!s:>5} {det.get('n_pd_weak','—')!s:>5} "
          f"{det.get('pd_amber_fired','—')!s:>8}")

# --- база-ставка скан: всеки петък 2016→2026, колко често PD-amber пътят пали ---
print("\n" + "=" * 100)
print("БАЗА-СТАВКА СКАН (седмично) — новият PD-amber път шумен ли е?")
print("=" * 100)
start = dt.date(2016, 1, 8)
end = dt.date(2026, 6, 19)
weeks, tally = 0, {"green": 0, "amber": 0, "red": 0, "null": 0}
pd_only, pd_dates = 0, []
d = start
while d <= end:
    ds = d.isoformat()
    lamp = L.lamp4_auctions(asof(ds))
    tally[lamp["status"]] += 1
    weeks += 1
    det = lamp.get("detail", {})
    if isinstance(det, dict) and det.get("pd_amber_fired"):
        pd_only += 1
        pd_dates.append((ds, [(t["tenor"], round(t["pd_share_z"], 1))
                              for t in det.get("pd_weak_tenors", [])]))
    d += dt.timedelta(days=7)
print(f"седмици: {weeks}  → 🟢 {tally['green']} ({100*tally['green']/weeks:.1f}%) · "
      f"🟡 {tally['amber']} ({100*tally['amber']/weeks:.1f}%) · "
      f"🔴 {tally['red']} ({100*tally['red']/weeks:.1f}%) · ⚪ {tally['null']}")
print(f"PD-amber път пали САМ (без btc breadth): {pd_only} седмици "
      f"({100*pd_only/weeks:.1f}% база)")
print("Примерни PD-amber седмици (дата → тенори с PD_z):")
for ds, tn in pd_dates[:14]:
    print(f"  {ds}  {tn}")
