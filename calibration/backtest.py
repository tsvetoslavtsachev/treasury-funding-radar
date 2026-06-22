"""Бектест харнес за gate-3 калибрация.

НЕ production. Тегли историята веднъж, реже я „към дата" (point-in-time, без
lookahead) и пуска СЪЩАТА production lamp логика (src/funding_radar/lamps.py) —
така валидираме реалния код, не препис. Печата таблица статус×епизод.

Run: FRED_API_KEY=... python calibration/backtest.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from funding_radar import lamps as L          # noqa: E402
from funding_radar.composite import composite  # noqa: E402
from funding_radar import sources as S         # noqa: E402

KEY = os.environ.get("FRED_API_KEY")
if not KEY:
    sys.exit("FRED_API_KEY липсва")

UA = {"User-Agent": "treasury-funding-radar-calib/0.1", "Accept": "application/json"}
HIST_START = "2015-01-01"   # покрива септ 2019, март 2020, 2025; OFR започва по-късно

# --- епизоди за калибрация (as-of дати) -------------------------------------
EPISODES = [
    ("2019-09-17", "Repo spike септ-2019 (SOFR 5.25)"),
    ("2019-09-18", "Repo spike +1 ден"),
    ("2020-03-18", "Dash-for-cash март-2020"),
    ("2024-06-14", "СПОКОЕН контрол"),
    ("2025-10-31", "SRF $29.4млрд (31.10.2025)"),
    ("2026-06-18", "Сега (live контрол)"),
]


# --------------------------------------------------------------------------- #
# Историческо теглене (FRED с date range)
# --------------------------------------------------------------------------- #
def get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def fred_hist(series_id: str) -> list[dict]:
    """Цяла история от HIST_START, ascending → [{date, value(float|None)}]."""
    q = urllib.parse.urlencode({
        "series_id": series_id, "api_key": KEY, "file_type": "json",
        "observation_start": HIST_START, "sort_order": "asc", "limit": 100000,
    })
    doc = get(f"https://api.stlouisfed.org/fred/series/observations?{q}")
    out = []
    for o in doc["observations"]:
        v = o.get("value")
        out.append({"date": o["date"], "value": None if v in (".", "", None) else float(v)})
    return out


# --------------------------------------------------------------------------- #
# As-of срезове (point-in-time)
# --------------------------------------------------------------------------- #
def desc_asof(series: list[dict], d: str) -> list[dict]:
    """Наблюдения с date<=d, сортирани descending (както production fetch)."""
    return sorted([o for o in series if o["date"] <= d], key=lambda o: o["date"], reverse=True)


def value_on(series: list[dict], d: str):
    """Последната non-null стойност с date<=d (или None)."""
    for o in desc_asof(series, d):
        if o["value"] is not None:
            return o["value"], o["date"]
    return None, None


# --------------------------------------------------------------------------- #
# Зареждане на всички серии веднъж
# --------------------------------------------------------------------------- #
print("Тегля история (FRED + TreasuryDirect + OFR)…", file=sys.stderr)
H = {sid: fred_hist(sid) for sid in (
    "H8B3092NCBA", "WRESBAL", "RRPONTSYD", "IOER", "IORB",
    "SOFR", "SOFR1", "SOFR25", "SOFR75", "SOFR99", "RPONTSYD", "RPONTTLD",
)}

auctions_all = S.fetch_auctions(
    base="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
    path="/v1/accounting/od/auctions_query", since=HIST_START, page_size=10000)

try:
    ofr_all = S.fetch_ofr("REPO-DVP_TV_TOT-P",
                          base="https://data.financialresearch.gov/v1",
                          path="/series/timeseries")
except Exception as e:
    print(f"OFR ERR: {e}", file=sys.stderr)
    ofr_all = []

# Лампа 5 ос-2 (позиция) — CFTC TFF leveraged-funds, no-auth (не иска FRED ключ)
try:
    cftc_all = S.fetch_cftc(base="https://publicreporting.cftc.gov", dataset="gpe5-46if",
                            codes=["042601", "044601", "043602", "043607", "020601", "020604"],
                            fields={"date": "report_date_as_yyyy_mm_dd",
                                    "code": "cftc_contract_market_code",
                                    "lev_long": "lev_money_positions_long",
                                    "lev_short": "lev_money_positions_short",
                                    "open_interest": "open_interest_all"}, limit=8000)
except Exception as e:
    print(f"CFTC ERR: {e}", file=sys.stderr)
    cftc_all = []
print(f"CFTC TFF: {cftc_all[0]['date'] if cftc_all else '—'} … "
      f"{cftc_all[-1]['date'] if cftc_all else '—'} (n={len(cftc_all)})", file=sys.stderr)

ofr_start = ofr_all[0]["date"] if ofr_all else "—"
print(f"OFR DVP история: {ofr_start} … {ofr_all[-1]['date'] if ofr_all else '—'} "
      f"(n={len(ofr_all)})", file=sys.stderr)
print(f"Аукциони: n={len(auctions_all)}, най-ранен {auctions_all[-1]['auction_date']}",
      file=sys.stderr)


# --------------------------------------------------------------------------- #
# Сглоби входовете за лампите при as-of дата
# --------------------------------------------------------------------------- #
def sofr_asof(d: str) -> dict | None:
    rate, rdate = value_on(H["SOFR"], d)
    if rate is None:
        return None
    return {
        "date": rdate, "rate": rate,
        "p1": value_on(H["SOFR1"], d)[0], "p25": value_on(H["SOFR25"], d)[0],
        "p75": value_on(H["SOFR75"], d)[0], "p99": value_on(H["SOFR99"], d)[0],
        "volume_bn": None,
    }


def iorb_obs_asof(d: str) -> list[dict]:
    # IORB съществува от 2021-07-29; преди това IOER е политиката
    src = "IORB" if d >= "2021-07-29" else "IOER"
    return desc_asof(H[src], d)


def auctions_asof(d: str) -> list[dict]:
    # огледало на production: trailing 400 дни преди as-of, descending
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=400)).isoformat()
    return [a for a in auctions_all if lo <= a["auction_date"] <= d]  # вече desc


def ofr_asof(d: str) -> list[dict]:
    return [o for o in ofr_all if o["date"] <= d]  # ascending


def cftc_asof(d: str) -> list[dict]:
    return [c for c in cftc_all if c["date"] <= d]  # ascending


THRESHOLDS = {
    "lamp2_reserve_floor_usd_tn": {"amber": 3.0, "red": 2.8},
    "lamp2_srf_repo_usd_bn": {"nonqe": {"amber": 5.0, "red": 20.0},
                              "qe": {"amber": 15.0, "red": 30.0}},
    "lamp3_sofr_iorb_bp": {"spread": {"amber": 5, "red": 15},
                           "tail": {"amber": 25, "red": 50},
                           "rolling": {"days": 5, "amber": 5, "red": 10}},
    "lamp5_cftc_leverage": {"pct_oi_loaded": 0.33, "pct_oi_moderate": 0.25,
                            "unwind_window_weeks": 3, "unwind_floor_pct_oi": 0.15,
                            "unwind_3w_amber": -0.08, "unwind_3w_red": -0.12},
}


def evaluate(d: str) -> list[dict]:
    srf_val, srf_date = value_on(H["RPONTSYD"], d)   # SRF/repo take-up прокси
    return [
        L.lamp1_bank_repo(desc_asof(H["H8B3092NCBA"], d)),
        L.lamp2_plumbing(desc_asof(H["WRESBAL"], d), desc_asof(H["RRPONTSYD"], d),
                         {"value": srf_val, "date": srf_date}, THRESHOLDS),
        L.lamp3_sofr(sofr_asof(d), iorb_obs_asof(d), THRESHOLDS, sofr_hist=desc_asof(H["SOFR"], d)),
        L.lamp4_auctions(auctions_asof(d)),
        L.lamp5_leverage(ofr_asof(d), cftc_asof(d), THRESHOLDS),
    ]


# --------------------------------------------------------------------------- #
# Таблица
# --------------------------------------------------------------------------- #
GLYPH = {"green": "🟢", "amber": "🟡", "red": "🔴", "null": "⚪"}


def cell(lamp: dict) -> str:
    g = GLYPH[lamp["status"]]
    det = lamp.get("detail", {})
    if lamp["id"] == 2:
        return f"{g} res{lamp['value']} srf{det.get('srf_repo_usd_bn')}"
    if lamp["id"] == 3:
        return f"{g} spr{det.get('sofr_minus_iorb_bp')} tail{det.get('tail_p99_minus_p25_bp')}"
    if lamp["id"] == 4:
        return f"{g} z{det.get('worst_bid_to_cover_z')}/{det.get('worst_term')}"
    if lamp["id"] == 5:
        pos = det.get("position_axis", {}) if isinstance(det, dict) else {}
        vol = det.get("volume_axis", {}) if isinstance(det, dict) else {}
        return f"{g} oi{pos.get('net_short_pct_oi')} vz{vol.get('volume_z_63d')}"
    if lamp["id"] == 1:
        return f"{g} p{lamp.get('percentile', {}).get('percentile')}"
    return g


print("\n" + "=" * 110)
print("БЕКТЕСТ — provisional прагове, point-in-time (текущата production логика)")
print("=" * 110)
hdr = f"{'as-of':<12} {'епизод':<32} {'L1 банк':<14} {'L2 plumb':<22} {'L3 sofr':<22} {'L4 auct':<20} {'L5 lev':<10} comp"
print(hdr)
print("-" * len(hdr))
for d, label in EPISODES:
    lampset = evaluate(d)
    comp = composite(lampset)
    cells = {l["id"]: cell(l) for l in lampset}
    print(f"{d:<12} {label:<30} {cells[1]:<12} {cells[2]:<20} {cells[3]:<20} "
          f"{cells[4]:<18} {cells[5]:<8} {comp['score']} {comp['verdict']}")

print("\nЛегенда: res=резерви($трлн) srf=RPONTSYD($млрд) spr=SOFR−IORB(bp) "
      "tail=p99−p25(bp) z=z-score")
