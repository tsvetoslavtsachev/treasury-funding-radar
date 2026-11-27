"""Лампа 4: TIPS и FRN отделно от номиналните (ПРОЛЕТБ2, 27.11.2026). Прекалибровка.

Пуска ИСТИНСКАТА функция на лампата (lamps._lamp4_core, с дилърския път) на всеки петък,
прозорец 400 дни назад до деня преди среза (както backfill.py), в четири варианта:
  смесено     както беше до 27.11.2026: TIPS и FRN в групата на номиналния срок
  номинални   само номиналните (TIPS и FRN извън лампата)
  с глас      TIPS и FRN в свои групи, които гласуват за цвета (отхвърлено: шумно)
  отделено    новото правило от 27.11.2026: свои групи, само за сведение (lamps._l4_group);
              гейтът е цветът и стойността да са точно като „номинални“
и таблира: базовите честоти в спокойни седмици (методът на calibration/lamp4_scan.py:
стресовите прозорци 09-10.2019 и 03-04.2020 са отделени), попаденията в стрес, известните
епизоди и колко често всяка група на TIPS/FRN би палила, ако гласуваше.

Пуск (живо, без ключ):  python calibration/lamp4_split_scan.py
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from funding_radar import lamps as L     # noqa: E402
from funding_radar import sources as S   # noqa: E402

TD_BASE, TD_PATH = "https://www.treasurydirect.gov/TA_WS", "/securities/search"
STRESS = [("2019-09-01", "2019-10-15"), ("2020-03-01", "2020-04-15")]
PERIODS = {"калибровката 2016-01..2026-06": ("2016-01-01", "2026-06-18"),
           "цялата история 2009-06..2026-11": ("2009-06-05", "2026-11-27")}
EPISODES = [("2013-07-05", "паниката от свиването, лято 2013"),
            ("2018-11-16", "ноември 2018"), ("2019-01-04", "декември 2018"),
            ("2019-09-20", "репо, септември 2019"), ("2020-03-20", "март 2020"),
            ("2021-03-05", "7-годишните, 25.02.2021"), ("2023-11-17", "30-годишните, 09.11.2023"),
            ("2024-01-26", "20-годишните, 01.2024"), ("2025-04-11", "април 2025"),
            ("2026-09-25", "10-годишният TIPS, 17.09.2026"), ("2026-11-27", "днес")]
VARIANTS = ("смесено", "номинални", "с глас", "отделено")


def in_stress(d: str) -> bool:
    return any(a <= d <= b for a, b in STRESS)


def fridays(a: str, b: str):
    d = dt.date.fromisoformat(a)
    d += dt.timedelta(days=(4 - d.weekday()) % 7)
    while d <= dt.date.fromisoformat(b):
        yield d
        d += dt.timedelta(days=7)


def core(rows, day):
    lo = (day - dt.timedelta(days=400)).isoformat()
    cut = (day - dt.timedelta(days=1)).isoformat()
    return L._lamp4_core([a for a in rows if lo <= a["auction_date"] <= cut])


def path_of(o) -> str:
    if o["status"] != "amber":
        return o["status"]
    return "amber-PD" if o["detail"].get("pd_amber_fired") else "amber-btc"


def main() -> int:
    print("Тегля TreasuryDirect…", file=sys.stderr)
    allr = S.fetch_auctions(base=TD_BASE, path=TD_PATH, since="2008-01-01")
    rows_of = {
        "смесено": [{**a, "kind": None} for a in allr],
        "номинални": [a for a in allr if a["kind"] == "nominal"],
        # свои групи с глас: TIPS/FRN като „номинални“ с име на групата, което носи вида
        "с глас": [a if a["kind"] == "nominal" else
                   {**a, "kind": None, "orig_term": f"{a['orig_term']} {a['kind']}"} for a in allr],
        "отделено": allr,
    }
    res = {v: {d.isoformat(): core(rows_of[v], d) for d in fridays("2009-06-05", "2026-11-27")}
           for v in VARIANTS}

    for pname, (a, b) in PERIODS.items():
        print(f"\n== {pname}: базови честоти в спокойни седмици / попадения в стрес")
        print(f"{'вариант':<11} {'седм.':>5} {'червено':>9} {'жълто':>8} {'жълто-btc':>10} "
              f"{'жълто-PD':>9} {'стрес: не-зелено':>17}")
        for v in VARIANTS:
            calm, stress = Counter(), Counter()
            for ds, o in res[v].items():
                if a <= ds <= b:
                    (stress if in_stress(ds) else calm)[path_of(o)] += 1
            n, ns = sum(calm.values()), sum(stress.values())
            amb = calm["amber-btc"] + calm["amber-PD"]

            def pct(k):
                return f"{100 * k / n:.1f}%"
            print(f"{v:<11} {n:>5} {pct(calm['red']):>9} {pct(amb):>8} {pct(calm['amber-btc']):>10} "
                  f"{pct(calm['amber-PD']):>9} {ns - stress['green']:>8}/{ns}")

    print("\n== Епизодите (цветът на петъка)")
    print(f"{'петък':<11} " + " ".join(f"{v:>10}" for v in VARIANTS) + "  епизод")
    for ds, name in EPISODES:
        print(f"{ds:<11} " + " ".join(f"{res[v][ds]['status']:>10}" for v in VARIANTS) + f"  {name}")

    print("\n== Групите на TIPS и FRN, ако гласуваха (2009-06..2026-11)")
    weak15, weak20, pdw = Counter(), Counter(), Counter()
    for o in res["с глас"].values():
        det = o["detail"] if isinstance(o["detail"], dict) else {}
        for w in det.get("weak_tenors", []):
            if " " in w["tenor"]:
                weak15[w["tenor"]] += 1
                weak20[w["tenor"]] += w["z"] <= -2
        for w in det.get("pd_weak_tenors", []):
            if " " in w["tenor"]:
                pdw[w["tenor"]] += 1
    seen = Counter()
    for o in res["отделено"].values():
        det = o["detail"] if isinstance(o["detail"], dict) else {}
        for e in det.get("context_tenors", []):
            seen[e["tenor"]] += 1
    n = len(res["отделено"])
    for g in sorted(set(seen) | set(weak15)):
        print(f"  {g:<16} оценена {seen[g]:>4}/{n} седм. · z≤−1,5 {weak15[g]:>3} · z≤−2 {weak20[g]:>3}"
              f" · дилърски {pdw[g]:>3}")

    ch = Counter((res["смесено"][k]["status"], res["отделено"][k]["status"]) for k in res["смесено"]
                 if res["смесено"][k]["status"] != res["отделено"][k]["status"])
    same = sum(1 for k, o in res["отделено"].items()
               if (o["status"], o["value"], o["as_of"]) ==
               (res["номинални"][k]["status"], res["номинални"][k]["value"], res["номинални"][k]["as_of"]))
    ctx = sum(1 for o in res["отделено"].values()
              if isinstance(o["detail"], dict) and o["detail"].get("context_tenors"))
    print(f"\nСмени на цвета смесено → отделено: {sum(ch.values())} {dict(ch)}")
    print(f"Отделено = номинални (цвят, стойност, дата): {same}/{n}; седмици с TIPS/FRN в детайла: {ctx}")
    ok = same == n
    print("ГЕЙТ:", "минава" if ok else "НЕ минава")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
