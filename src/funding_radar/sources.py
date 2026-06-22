"""Fetchers за резолвнатите източници. Всеки нормализира + записва health.

Resolved live 2026-06-22 (gate 1):
  FRED (key от env) · NY Fed SOFR (no-auth) · TreasuryDirect auctions (no-auth) ·
  OFR STFM (no-auth). NY Fed SRF repo-ops endpoint = open thread (вж sources.yaml).
"""
from __future__ import annotations

import os
import urllib.parse

from .common import FetchError, HealthBook, assert_keys, http_get_json


# --------------------------------------------------------------------------- #
# FRED — primary за лампа 1 + FRED-страните на 2/3 + context
# --------------------------------------------------------------------------- #
def fetch_fred(series_id: str, *, base: str, limit: int = 80) -> list[dict]:
    """Последните `limit` наблюдения, descending. Връща [{date, value}] (float|None).

    Ключът ЧЕТЕ от env (FRED_API_KEY) — никога не се пише в код/commit.
    """
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise FetchError("FRED_API_KEY липсва в средата")
    q = urllib.parse.urlencode({
        "series_id": series_id, "api_key": key, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    })
    doc = http_get_json(f"{base}/series/observations?{q}")
    assert_keys(doc, ["observations"], f"FRED:{series_id}")
    out = []
    for o in doc["observations"]:
        v = o.get("value")
        out.append({"date": o.get("date"), "value": None if v in (".", "", None) else float(v)})
    return out


def latest(obs: list[dict]) -> dict:
    """Първият non-null ред (списъкът е desc) → {date, value}."""
    for o in obs:
        if o["value"] is not None:
            return o
    return {"date": None, "value": None}


# --------------------------------------------------------------------------- #
# NY Fed — SOFR + персентилно разпределение (лампа 3), no-auth
# --------------------------------------------------------------------------- #
def fetch_nyfed_sofr(*, base: str, path: str) -> dict:
    doc = http_get_json(f"{base}{path}")
    assert_keys(doc, ["refRates"], "NYFed:sofr")
    r = doc["refRates"][0]
    assert_keys(r, ["effectiveDate", "percentRate", "percentPercentile99"], "NYFed:sofr.row")
    return {
        "date": r["effectiveDate"],
        "rate": r["percentRate"],
        "p1": r.get("percentPercentile1"),
        "p25": r.get("percentPercentile25"),
        "p75": r.get("percentPercentile75"),
        "p99": r.get("percentPercentile99"),
        "volume_bn": r.get("volumeInBillions"),
    }


# --------------------------------------------------------------------------- #
# TreasuryDirect — аукциони (лампа 4), no-auth
# --------------------------------------------------------------------------- #
def fetch_auctions(*, base: str, path: str, since: str, page_size: int = 300) -> list[dict]:
    """Settled аукциони от `since` (bid_to_cover не-null), нормализирани."""
    q = urllib.parse.urlencode({
        "fields": "auction_date,security_type,security_term,original_security_term,"
                  "bid_to_cover_ratio,primary_dealer_accepted,total_accepted",
        "filter": f"auction_date:gte:{since}",
        "sort": "-auction_date",
        "page[size]": page_size,
    }, safe=":")
    doc = http_get_json(f"{base}{path}?{q}")
    assert_keys(doc, ["data"], "Treasury:auctions")
    out = []
    for d in doc["data"]:
        btc = d.get("bid_to_cover_ratio")
        if btc in (None, "null", ""):
            continue
        pda = d.get("primary_dealer_accepted")
        tot = d.get("total_accepted")
        try:
            pd_share = (float(pda) / float(tot)) if pda not in (None, "null", "") and \
                       tot not in (None, "null", "", "0") else None
        except (ValueError, ZeroDivisionError):
            pd_share = None
        out.append({
            "auction_date": d.get("auction_date"),
            "security_type": d.get("security_type"),
            "term": d.get("security_term"),
            "orig_term": d.get("original_security_term"),  # събира reopening-ите в тенора
            "bid_to_cover": float(btc),
            "primary_dealer_share": pd_share,
        })
    return out


# --------------------------------------------------------------------------- #
# OFR STFM — sponsored/DVP repo (лампа 5), no-auth
# --------------------------------------------------------------------------- #
def fetch_ofr(mnemonic: str, *, base: str, path: str) -> list[dict]:
    """OFR timeseries → [{date, value}] (възходящо по дата)."""
    q = urllib.parse.urlencode({"mnemonic": mnemonic})
    doc = http_get_json(f"{base}{path}?{q}")
    if not isinstance(doc, list):
        raise FetchError(f"OFR:{mnemonic} неочакван shape {type(doc).__name__}")
    return [{"date": p[0], "value": p[1]} for p in doc if isinstance(p, list) and len(p) == 2]


# --------------------------------------------------------------------------- #
# CFTC TFF — leveraged-funds нетна къса в UST фючърси (лампа 5 ос-2), no-auth
#
# Socrata директен fetch (standalone Зона-1 принцип — НЕ кросрепо data-core).
# Идентичност: ПИННАТ по cftc_contract_market_code, НЕ по име (WTI/LIKE урокът;
# 020604 носи 2 имена под 1 код). Агрегира 6-те UST кода в 1 седмична серия.
# --------------------------------------------------------------------------- #
def fetch_cftc(*, base: str, dataset: str, codes: list[str], fields: dict,
               limit: int = 1500) -> list[dict]:
    """CFTC TFF Leveraged Funds нетна къса (short−long) + OI, агрегат на UST комплекса.

    Връща ascending [{date, net_short, oi, pct_oi}] (1 ред/седмичен COT report).
    pct_oi = нетна къса / open interest (regime-robust мярка за 'заредено').
    """
    f = fields
    inlist = ",".join(f"'{c}'" for c in codes)
    params = {
        "$select": ",".join((f["date"], f["code"], f["lev_long"],
                             f["lev_short"], f["open_interest"])),
        "$where": f"{f['code']} in({inlist})",
        "$order": f"{f['date']} DESC",
        "$limit": limit,
    }
    rows = http_get_json(f"{base}/resource/{dataset}.json?{urllib.parse.urlencode(params)}")
    if not isinstance(rows, list) or not rows:
        raise FetchError(f"CFTC:{dataset} празен/неочакван отговор")
    assert_keys(rows[0], [f["date"], f["code"], f["lev_long"], f["lev_short"],
                          f["open_interest"]], f"CFTC:{dataset}")
    # identity guard: само пиннати коди (rename/splice защита)
    unexpected = {r.get(f["code"]) for r in rows} - set(codes)
    if unexpected:
        raise FetchError(f"CFTC:{dataset} неочаквани коди {sorted(unexpected)} (pin-by-code)")
    agg: dict[str, list[int]] = {}
    for r in rows:
        d = r[f["date"]][:10]
        a = agg.setdefault(d, [0, 0, 0])
        a[0] += int(float(r[f["lev_long"]]))
        a[1] += int(float(r[f["lev_short"]]))
        a[2] += int(float(r.get(f["open_interest"]) or 0))
    out = []
    for d in sorted(agg):
        lng, sht, oi = agg[d]
        ns = sht - lng
        out.append({"date": d, "net_short": ns, "oi": oi,
                    "pct_oi": round(ns / oi, 4) if oi else None})
    return out
