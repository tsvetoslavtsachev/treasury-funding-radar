r"""Дописване назад на историята на лампите (ПРОЛЕТР2, 25.11.2026).

Смята петте лампи за всеки минал ден със СЪЩИТЕ функции като живия пуск
(`lamps.lamp1_bank_repo` ... `lamp5_leverage`, праговете от config/sources.yaml) и
ги слива в data/lamps_history.csv с белег „дописан“. Живите редове не се пипат.

Какво е „ден d“: картината, която вечерният пуск на радара (около 20:30 UTC) би видял
в ден d. За всеки източник това е:
  FRED       ALFRED-реколтата, известна до края на d-1 (realtime_start <= d-1 <= realtime_end).
             H.8 (петък 21:15 UTC) и H.4.1 (четвъртък 21:30 UTC) излизат след вечерния
             пуск, затова се броят от следващия ден. Така ревизиите не се вмъкват назад.
  NY Fed     SOFR с effectiveDate <= d-1 (публикува се сутринта на следващия работен ден).
  Fiscal Data аукциони с auction_date <= d-1 (реколти няма); прозорецът е 400 дни назад
             от d и една страница от 300 реда, точно както живия пуск.
  OFR        точки с дата <= 2 работни дни преди d (реколти няма).
  CFTC       отчети с дата <= d-4 (вторникът излиза в петък следобед).
Лаговете са сверени с git снимките на lamps.json (`--verify-git`, 111 дни от 22.06.2026);
разминаванията идват от часа на пуска, празниците и ревизиите на OFR и са описани в
отчета на ПРОЛЕТР2 (C:\Projects\_orchestration\prolet\PROLETR2-OTCHET.md).

Употреба (нужен е FRED_API_KEY в средата):
  python -m funding_radar.backfill --start 2024-11-25 --end 2026-11-24            # сух ход
  python -m funding_radar.backfill --start 2024-11-25 --end 2026-11-24 --write
  python -m funding_radar.backfill --verify-git                                   # сверка
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

from . import history as Hs
from . import lamps as L
from . import sources as S
from .common import FetchError, http_get_json
from .run import DATA, ROOT, _load_config

OFR_LAG_BDAYS = 2
CFTC_LAG_DAYS = 4
AUCTION_LAG_DAYS = 1
AUCTION_PAGE = 300         # живият пуск взима една страница от 300 реда (sources.fetch_auctions)
FRED_LIMIT = 80            # колкото тегли живият пуск (sources.fetch_fred)
LAMP_SERIES = ("bank_repo", "on_rrp", "reserves", "rpontsyd", "iorb", "sofr_hist")


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _minus(day: str, n: int) -> str:
    return (_d(day) - dt.timedelta(days=n)).isoformat()


def _minus_bd(day: str, n: int) -> str:
    """n работни дни (пон-пет) назад; празниците не се броят отделно."""
    x = _d(day)
    while n > 0:
        x -= dt.timedelta(days=1)
        if x.weekday() < 5:
            n -= 1
    return x.isoformat()


# --------------------------------------------------------------------------- #
# Теглене на историята (веднъж)
# --------------------------------------------------------------------------- #
def fred_vintages(sid: str, base: str, obs_start: str, rt_start: str) -> list[dict]:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise FetchError("FRED_API_KEY липсва в средата")
    q = urllib.parse.urlencode({
        "series_id": sid, "api_key": key, "file_type": "json",
        "observation_start": obs_start, "realtime_start": rt_start,
        "realtime_end": "9999-12-31", "limit": 100000})
    doc = http_get_json(f"{base}/series/observations?{q}")
    # мерната единица се сменя между реколтите (WRESBAL: милиарди до 12.11.2025, милиони
    # от 13.11.2025); всяка точка се привежда към единицата на най-новата реколта
    qs = urllib.parse.urlencode({"series_id": sid, "api_key": key, "file_type": "json",
                                 "realtime_start": rt_start, "realtime_end": "9999-12-31"})
    units = [(r["realtime_start"], r["realtime_end"], r["units"])
             for r in http_get_json(f"{base}/series?{qs}")["seriess"]]
    out = []
    for o in doc["observations"]:
        v = o.get("value")
        val = None if v in (".", "", None) else float(v)
        if val is not None:
            val *= unit_factor(units, o["realtime_start"])
        out.append({"date": o["date"], "rs": o["realtime_start"], "re": o["realtime_end"],
                    "value": val})
    return out


_SCALE = {"thousands": 1e-3, "millions": 1.0, "billions": 1e3, "trillions": 1e6}


def _scale(unit: str) -> float | None:
    u = unit.lower()
    return next((f for k, f in _SCALE.items() if u.startswith(k)), None)


def unit_factor(units: list[tuple[str, str, str]], rs: str) -> float:
    """Множител от единицата, валидна към `rs`, към единицата на най-новата реколта."""
    if not units:
        return 1.0
    latest = max(units)[2]
    here = next((u for a, b, u in units if a <= rs <= b), latest)
    f_here, f_latest = _scale(here), _scale(latest)
    if f_here is None or f_latest is None or here == latest:
        return 1.0
    return f_here / f_latest


def nyfed_sofr_hist(base: str, start: str, end: str) -> list[dict]:
    q = urllib.parse.urlencode({"startDate": start, "endDate": end})
    doc = http_get_json(f"{base}/rates/secured/sofr/search.json?{q}")
    out = []
    for r in doc.get("refRates", []):
        out.append({"date": r["effectiveDate"], "rate": r["percentRate"],
                    "p1": r.get("percentPercentile1"), "p25": r.get("percentPercentile25"),
                    "p75": r.get("percentPercentile75"), "p99": r.get("percentPercentile99"),
                    "volume_bn": r.get("volumeInBillions")})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def fetch_all(cfg: dict, start: str, end: str) -> dict:
    src = cfg["sources"]
    fred, nyfed, tre, ofr, cftc = (src[k] for k in ("fred", "nyfed", "treasury", "ofr", "cftc"))
    obs_start = _minus(start, 800)
    raw = {"fred": {}}
    for key in LAMP_SERIES:
        sid = fred["series"][key]["id"]
        raw["fred"][key] = fred_vintages(sid, fred["base"], obs_start, _minus(start, 2))
    raw["sofr"] = nyfed_sofr_hist(nyfed["base"], _minus(start, 10), end)
    raw["auctions"] = S.fetch_auctions(base=tre["base"], path=tre["auctions"],
                                       since=_minus(start, 410), page_size=10000)
    raw["ofr"] = S.fetch_ofr(ofr["mnemonics"]["dvp_total_volume"],
                             base=ofr["base"], path=ofr["series_timeseries"])
    raw["cftc"] = S.fetch_cftc(base=cftc["base"], dataset=cftc["dataset"],
                               codes=cftc["ust_codes"], fields=cftc["fields"], limit=50000)
    return raw


# --------------------------------------------------------------------------- #
# Срезове към ден d
# --------------------------------------------------------------------------- #
def fred_asof(vint: list[dict], cut: str, limit: int = FRED_LIMIT) -> list[dict]:
    """Реколтата към `cut`: по едно наблюдение на дата, descending, първите `limit`."""
    rows = [{"date": o["date"], "value": o["value"]} for o in vint
            if o["rs"] <= cut <= o["re"] and o["date"] <= cut]
    rows.sort(key=lambda o: o["date"], reverse=True)
    return rows[:limit]


def inputs_for(raw: dict, day: str) -> dict:
    cut = _minus(day, 1)
    f = {k: fred_asof(v, cut) for k, v in raw["fred"].items()}
    sofr = next((r for r in raw["sofr"] if r["date"] <= cut), None)
    a_cut = _minus(day, AUCTION_LAG_DAYS)
    lo = _minus(day, 400)
    auctions = [a for a in raw["auctions"] if lo <= a["auction_date"] <= a_cut][:AUCTION_PAGE]
    ofr = [o for o in raw["ofr"] if o["date"] <= _minus_bd(day, OFR_LAG_BDAYS)]
    cftc = [c for c in raw["cftc"] if c["date"] <= _minus(day, CFTC_LAG_DAYS)]
    srf = S.latest(f["rpontsyd"])
    return {"fred": f, "sofr": sofr, "auctions": auctions, "ofr": ofr, "cftc": cftc,
            "srf": {"value": srf["value"], "date": srf["date"]}}


def lamps_for(raw: dict, day: str, th: dict) -> list[dict]:
    """Същият ред като run.build: петте лампи за ден d."""
    i = inputs_for(raw, day)
    f = i["fred"]
    return [
        L.lamp1_bank_repo(f["bank_repo"]),
        L.lamp2_plumbing(f["reserves"], f["on_rrp"], i["srf"], th),
        L.lamp3_sofr(i["sofr"], f["iorb"], th, sofr_hist=f["sofr_hist"]),
        L.lamp4_auctions(i["auctions"], today=day),
        L.lamp5_leverage(i["ofr"], i["cftc"], th),
    ]


def days(start: str, end: str) -> list[str]:
    a, b = _d(start), _d(end)
    return [(a + dt.timedelta(days=n)).isoformat() for n in range((b - a).days + 1)]


# --------------------------------------------------------------------------- #
# Сверка с git снимките на lamps.json
# --------------------------------------------------------------------------- #
def git_snapshots() -> list[tuple[str, dict]]:
    """Последната снимка на lamps.json за всеки UTC ден: [(day, lamps.json)]."""
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True).stdout
    hashes = git("log", "--format=%H", "--", "data/lamps.json").decode().split()
    by_day: dict[str, dict] = {}
    for h in reversed(hashes):            # от най-стария към най-новия: последният в деня печели
        try:
            doc = json.loads(git("show", f"{h}:data/lamps.json").decode("utf-8"))
        except ValueError:
            continue
        by_day[doc["generated_at"][:10]] = doc
    return sorted(by_day.items())


def compare(live: list[dict], back: list[dict]) -> dict:
    out = {}
    for a, b in zip(live, back):
        av, bv = a.get("value"), b.get("value")
        same_v = (av == bv) or (isinstance(av, (int, float)) and isinstance(bv, (int, float))
                                and abs(av - bv) <= 1e-6 * max(1.0, abs(av)))
        out[a["id"]] = {"value": same_v, "as_of": a.get("as_of") == b.get("as_of"),
                        "status": a.get("status") == b.get("status")}
    return out


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main(argv=None) -> int:
    _utf8()
    p = argparse.ArgumentParser()
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--write", action="store_true")
    p.add_argument("--verify-git", action="store_true")
    p.add_argument("--out", default=str(DATA / "lamps_history.csv"))
    a = p.parse_args(argv)
    cfg = _load_config()
    th = cfg["thresholds"]

    if a.verify_git:
        snaps = git_snapshots()
        start, end = snaps[0][0], snaps[-1][0]
        raw = fetch_all(cfg, start, end)
        tally: dict[int, dict[str, int]] = {}
        misses = []
        for day, doc in snaps:
            # снимките преди лампа 4 с today нямат as_of_kind; сравняваме само ядрото
            res = compare(doc["lamps"], lamps_for(raw, day, th))
            for lid, r in res.items():
                t = tally.setdefault(lid, {"n": 0, "value": 0, "as_of": 0, "status": 0})
                t["n"] += 1
                for k in ("value", "as_of", "status"):
                    t[k] += r[k]
                if not all(r.values()):
                    misses.append((day, lid, r))
        print(f"git снимки: {len(snaps)} дни, {start} … {end}")
        for lid in sorted(tally):
            t = tally[lid]
            print(f"  лампа {lid}: стойност {t['value']}/{t['n']} · as_of {t['as_of']}/{t['n']}"
                  f" · цвят {t['status']}/{t['n']}")
        for day, lid, r in misses[-15:]:
            print(f"  разминаване {day} лампа {lid}: " + ", ".join(k for k, ok in r.items() if not ok))
        return 0

    raw = fetch_all(cfg, a.start, a.end)
    new = []
    for day in days(a.start, a.end):
        new += Hs.rows_from_lamps(lamps_for(raw, day, th), day, Hs.BACKFILL)
    path = pathlib.Path(a.out)
    rows = Hs.merge(Hs.load(path), new)
    print(f"дописани {len(new)} реда за {a.start} … {a.end}; във файла ще са {len(rows)}")
    if a.write:
        Hs.write(path, rows)
        print(f"записано: {path}")
    else:
        print("(сух ход; ползвай --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
