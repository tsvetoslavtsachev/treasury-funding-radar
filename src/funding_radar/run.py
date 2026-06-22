"""Оркестратор: fetch → лампи → composite → JSON изходи.

Per-source error isolation: счупен източник → health.error + null лампа, НЕ сваля
целия run (production-safety). Изходи в data/:
  lamps.json · composite.json · funding_state.json (handoff) · health.json
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys

import yaml

from . import __version__
from .common import FetchError, HealthBook
from .composite import composite
from . import lamps as L
from . import sources as S

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "sources.yaml"
DATA = ROOT / "data"


def _load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build(cfg: dict) -> dict:
    health = HealthBook()
    fred = cfg["sources"]["fred"]
    nyfed = cfg["sources"]["nyfed"]
    tre = cfg["sources"]["treasury"]
    ofr = cfg["sources"]["ofr"]
    th = cfg["thresholds"]

    def fred_series(key: str) -> list[dict]:
        sid = fred["series"][key]["id"]
        try:
            obs = S.fetch_fred(sid, base=fred["base"])
            health.ok(f"fred:{key}", S.latest(obs)["date"])
            return obs
        except FetchError as e:
            health.error(f"fred:{key}", str(e))
            return []

    # --- fetch (всеки изолиран) ---
    bank_repo = fred_series("bank_repo")
    rrp = fred_series("on_rrp")
    reserves = fred_series("reserves")
    rpontsyd = fred_series("rpontsyd")    # SRF/repo take-up прокси (лампа 2)
    iorb = fred_series("iorb")
    sofr_hist = fred_series("sofr_hist")  # FRED SOFR за rolling-устойчивост (лампа 3 v1.1)
    tga = fred_series("tga")
    dgs10 = fred_series("dgs10")
    dgs30 = fred_series("dgs30")

    try:
        sofr = S.fetch_nyfed_sofr(base=nyfed["base"], path=nyfed["sofr"])
        health.ok("nyfed:sofr", sofr["date"])
    except FetchError as e:
        sofr = None
        health.error("nyfed:sofr", str(e))

    since = (_dt.date.today() - _dt.timedelta(days=400)).isoformat()
    try:
        auctions = S.fetch_auctions(base=tre["base"], path=tre["auctions"], since=since)
        health.ok("treasury:auctions", auctions[0]["auction_date"] if auctions else None)
    except FetchError as e:
        auctions = []
        health.error("treasury:auctions", str(e))

    try:
        ofr_obs = S.fetch_ofr(ofr["mnemonics"]["dvp_total_volume"],
                              base=ofr["base"], path=ofr["series_timeseries"])
        health.ok("ofr:dvp", ofr_obs[-1]["date"] if ofr_obs else None)
    except FetchError as e:
        ofr_obs = []
        health.error("ofr:dvp", str(e))

    cftc = cfg["sources"]["cftc"]              # лампа 5 ос-2 (позиция), no-auth Socrata
    try:
        cftc_obs = S.fetch_cftc(base=cftc["base"], dataset=cftc["dataset"],
                                codes=cftc["ust_codes"], fields=cftc["fields"])
        health.ok("cftc:tff_lev", cftc_obs[-1]["date"] if cftc_obs else None)
    except FetchError as e:
        cftc_obs = []
        health.error("cftc:tff_lev", str(e))

    # SRF/repo take-up = FRED RPONTSYD (резолвнат gate-3); {value, date} за QE-логиката
    srf_latest = S.latest(rpontsyd)
    srf = {"value": srf_latest["value"], "date": srf_latest["date"]}

    # --- лампи ---
    lamp_list = [
        L.lamp1_bank_repo(bank_repo),
        L.lamp2_plumbing(reserves, rrp, srf, th),
        L.lamp3_sofr(sofr, iorb, th, sofr_hist=sofr_hist),
        L.lamp4_auctions(auctions),
        L.lamp5_leverage(ofr_obs, cftc_obs, th),
    ]
    comp = composite(lamp_list)

    def _ctx(obs):
        o = S.latest(obs)
        return {"value": o["value"], "as_of": o["date"]}

    context = {"tga_usd_mn": _ctx(tga), "dgs10": _ctx(dgs10), "dgs30": _ctx(dgs30)}
    generated_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    return {
        "schema_version": cfg["schema_version"],
        "version": __version__,
        "generated_at": generated_at,
        "lamps": lamp_list,
        "composite": comp,
        "context": context,
        "health": health.to_dict(),
    }


def _write(name: str, obj) -> None:
    DATA.mkdir(exist_ok=True)
    with open(DATA / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main() -> int:
    # Windows CP1252 конзолата чупи кирилица/em-dash → форсирай UTF-8 (sibling repo gotcha)
    for stream in (sys.stdout, sys.stderr):
        if getattr(stream, "encoding", "").lower() != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    cfg = _load_config()
    result = build(cfg)
    _write("lamps.json", {k: result[k] for k in
                          ("schema_version", "version", "generated_at", "lamps", "health")})
    _write("composite.json", {k: result[k] for k in
                              ("schema_version", "generated_at", "composite", "context")})
    # funding_state.json — handoff (vrm-state модел) за 3-та консуматора
    _write("funding_state.json", {
        "schema_version": result["schema_version"],
        "as_of": result["generated_at"],
        "composite_score": result["composite"]["score"],
        "verdict": result["composite"]["verdict"],
        "lamp_status": {l["id"]: l["status"] for l in result["lamps"]},
        "any_dead_source": result["health"]["any_dead"],
    })
    _write("health.json", result["health"])
    c = result["composite"]
    print(f"composite {c['score']} — {c['verdict']} "
          f"(reds={c['reds']} ambers={c['ambers']} null={c['null_lamps']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
