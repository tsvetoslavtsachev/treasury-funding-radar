"""Лампа 5 (две оси) point-in-time валидация — no-auth (CFTC + OFR, БЕЗ FRED).

Тегли реалната CFTC TFF leveraged-funds история + OFR DVP обема, реже ги към
as-of дата (без lookahead) и пуска СЪЩАТА production lamp5_leverage логика.
Доказва централната претенция: март-2020 трябва да светне (дупката на обемната
ос — обемът беше висок, позицията се разпадаше).

Run: python calibration/lamp5_detail.py   (no key)
"""
from __future__ import annotations

import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from funding_radar import lamps as L          # noqa: E402
from funding_radar import sources as S         # noqa: E402

CFG = yaml.safe_load(open(os.path.join(ROOT, "config", "sources.yaml"), encoding="utf-8"))
TH = CFG["thresholds"]
C = CFG["sources"]["cftc"]
O = CFG["sources"]["ofr"]

EPISODES = [
    ("2019-09-17", "Repo spike септ-2019 (lamp2/3 епизод)"),
    ("2020-02-18", "Феб-2020 връх (заредено, преди unwind)"),
    ("2020-03-10", "Март-2020 unwind седмица 1"),
    ("2020-03-17", "Март-2020 unwind седмица 2 (dash-for-cash)"),
    ("2020-03-24", "Март-2020 unwind седмица 3"),
    ("2024-06-14", "СПОКОЕН контрол"),
    ("2025-09-02", "Рекордна нетна къса (заредено)"),
    ("2026-06-09", "Сега (live)"),
]

print("Тегля CFTC TFF (no-auth) + OFR DVP (no-auth)…", file=sys.stderr)
cftc_all = S.fetch_cftc(base=C["base"], dataset=C["dataset"],
                        codes=C["ust_codes"], fields=C["fields"], limit=8000)
try:
    ofr_all = S.fetch_ofr(O["mnemonics"]["dvp_total_volume"],
                          base=O["base"], path=O["series_timeseries"])
except Exception as e:
    print(f"OFR ERR: {e}", file=sys.stderr)
    ofr_all = []
print(f"CFTC: {cftc_all[0]['date']} … {cftc_all[-1]['date']} (n={len(cftc_all)})", file=sys.stderr)
print(f"OFR DVP: {ofr_all[0]['date'] if ofr_all else '—'} … "
      f"{ofr_all[-1]['date'] if ofr_all else '—'} (n={len(ofr_all)})", file=sys.stderr)


def cftc_asof(d):
    return [c for c in cftc_all if c["date"] <= d]


def ofr_asof(d):
    return [o for o in ofr_all if o["date"] <= d]


GLYPH = {"green": "🟢", "amber": "🟡", "red": "🔴", "null": "⚪"}
print("\n" + "=" * 108)
print("ЛАМПА 5 (две оси) — point-in-time, production логика")
print("=" * 108)
hdr = f"{'as-of':<12} {'епизод':<40} {'статус':<8} {'pct_oi':>7} {'3w%chg':>8} {'vol_z':>7}  fired / context"
print(hdr)
print("-" * len(hdr))
for d, label in EPISODES:
    lamp = L.lamp5_leverage(ofr_asof(d), cftc_asof(d), TH)
    det = lamp["detail"]
    pos = det.get("position_axis", {}) if isinstance(det, dict) else {}
    vol = det.get("volume_axis", {}) if isinstance(det, dict) else {}
    fired = ",".join(det.get("fired", [])) if isinstance(det, dict) else ""
    ctx = ",".join(det.get("context", [])) if isinstance(det, dict) else ""
    tag = fired + (f"  [ctx: {ctx}]" if ctx else "")
    pct = pos.get("net_short_pct_oi")
    chg = pos.get("net_short_3w_chg")
    vz = vol.get("volume_z_63d")
    print(f"{d:<12} {label:<40} {GLYPH[lamp['status']]:<7} "
          f"{('—' if pct is None else f'{pct:.3f}'):>7} "
          f"{('—' if chg is None else f'{chg:+.3f}'):>8} "
          f"{('—' if vz is None else f'{vz:+.2f}'):>7}  {tag}")

print("\nОчаквано: март-2020 трите седмици = 🔴 (unwind_red, дори при висок/липсващ обем);")
print("спокоен контрол = 🟢; рекордна/сега заредена = 🟢 + [ctx: loaded_gun] (не вечен amber);")
print("септ-2019 = чисто (lamp2/3 епизод). Amber се пази за ПРОМЯНА (unwind / движещ се обем).")
