"""Сверка на лампа 4: Fiscal Data (старият източник) срещу TreasuryDirect (новият, 27.11.2026).

Две нива, и двете на целия общ период (от 05.2008 до последния резултат на Fiscal Data):
  1. Ред по ред: ключ (auction_date, cusip); сравняват се тип, срок, оригинален срок,
     bid-to-cover и PD-дял (както ги нормализира радарът).
  2. Лампа по лампа: _lamp4_core на седмичните срезове (петък), прозорец 400 дни назад, както
     в backfill.py, от двата източника; сравнява се целият изход (цвят, стойност, детайл).

Гейт: 0 разминавания на ред и на лампа; редовете само във Fiscal Data са всичките
технически (оферта под 1 млрд.: TD четецът ги маха, Fiscal Data ги има); 0 само в TD.

Пуск (живо, без ключ):  python calibration/lamp4_td_parity.py
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import urllib.parse                      # noqa: E402

from funding_radar import lamps as L     # noqa: E402
from funding_radar import sources as S   # noqa: E402
from funding_radar.common import http_get_json  # noqa: E402

LO = "2008-05-01"
TD_BASE, TD_PATH = "https://www.treasurydirect.gov/TA_WS", "/securities/search"
FIELDS = ("security_type", "kind", "term", "orig_term", "bid_to_cover", "primary_dealer_share")


def parse_with_min_offering(raw: list[dict], floor: float) -> list[dict]:
    keep = S._TD_MIN_OFFERING
    try:
        S._TD_MIN_OFFERING = floor
        return S.parse_td_auctions(raw, LO)
    finally:
        S._TD_MIN_OFFERING = keep


def main() -> int:
    print("Тегля Fiscal Data…", file=sys.stderr)
    fd_all = S.fetch_auctions_fiscaldata(since=LO, page_size=10000)
    fd = {(a["auction_date"], a["cusip"]): a for a in fd_all
          if a["security_type"] in L._COUPON_TYPES}
    print("Тегля TreasuryDirect…", file=sys.stderr)
    raw = []
    for t in S.TD_AUCTION_TYPES:
        q = urllib.parse.urlencode({"format": "json", "type": t})
        raw += http_get_json(f"{TD_BASE}{TD_PATH}?{q}", timeout=180)
    td_all = S.parse_td_auctions(raw, LO)             # точно това, което fetch_auctions връща
    td = {(a["auction_date"], a["cusip"]): a for a in td_all}
    # техническите: редовете, които четецът маха само заради офертата под 1 млрд.
    tech = {(a["auction_date"], a["cusip"]) for a in parse_with_min_offering(raw, 0.0)} - set(td)
    hi = max(k[0] for k in fd)

    td_in = {k for k in td if k[0] <= hi}
    only_fd, only_td = sorted(set(fd) - td_in), sorted(td_in - set(fd))
    both = sorted(set(fd) & td_in)
    row_mis = []
    for k in both:
        for f in FIELDS:
            a, b = fd[k][f], td[k][f]
            same = (a == b) if not isinstance(a, float) or b is None else abs(a - b) < 1e-12
            if not same:
                row_mis.append((k, f, a, b))

    # лампа по лампа: седмични срезове (петък), прозорецът на backfill.py
    # редът на входа е като в живия пуск (при два аукциона от един срок в един ден той решава
    # кой е „последен“): Fiscal Data както идва (desc), TD както го връща fetch_auctions
    fd_rows = [a for a in fd_all if a["security_type"] in L._COUPON_TYPES
               and (a["auction_date"], a["cusip"]) not in tech]
    fd_rows_with_tech = [a for a in fd_all if a["security_type"] in L._COUPON_TYPES]
    td_rows = [a for a in td_all if a["auction_date"] <= hi]
    d = dt.date.fromisoformat("2009-06-05")
    end = dt.date.fromisoformat(hi) + dt.timedelta(days=7)
    cuts = lamp_mis = tech_diff = 0
    first_mis = None
    colors = {}

    def core(rows, day):
        lo = (day - dt.timedelta(days=400)).isoformat()
        cut = (day - dt.timedelta(days=1)).isoformat()
        return L._lamp4_core([a for a in rows if lo <= a["auction_date"] <= cut])

    while d <= end:
        a, b = core(fd_rows, d), core(td_rows, d)
        cuts += 1
        colors[b["status"]] = colors.get(b["status"], 0) + 1
        if json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str):
            lamp_mis += 1
            first_mis = first_mis or (d.isoformat(), a["status"], b["status"])
        if core(fd_rows_with_tech, d)["status"] != a["status"]:
            tech_diff += 1
        d += dt.timedelta(days=7)

    print(f"Общ период: {LO} .. {hi} (последният резултат на Fiscal Data)")
    print(f"Купонни аукциона с резултат: Fiscal Data {len(fd)} · TreasuryDirect {len(td_in)} · общи {len(both)}")
    print(f"Само във Fiscal Data: {len(only_fd)}, от тях технически (оферта под 1 млрд.): "
          f"{len(set(only_fd) & tech)} {only_fd}")
    print(f"Само в TreasuryDirect: {len(only_td)} {only_td[:10]}")
    print(f"Разминавания на ред (тип, срок, ориг. срок, bid-to-cover, PD-дял): {len(row_mis)} "
          f"{row_mis[:5]}")
    print(f"Седмични срезове на лампа 4: {cuts}; различен изход: {lamp_mis} {first_mis or ''}")
    print(f"  цветовете (TD): {colors}")
    print(f"  срезове, на които техническите редове биха сменили цвета: {tech_diff}")
    newer = sorted(k for k in td if k[0] > hi)
    print(f"След {hi} само TreasuryDirect: {len(newer)} аукциона, последен {newer[-1][0] if newer else '-'}")
    ok = not row_mis and not lamp_mis and not only_td and set(only_fd) <= tech
    print("ГЕЙТ:", "минава" if ok else "НЕ минава")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
