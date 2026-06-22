"""5-те лампи. Всяка → {id, name, value, percentile?, threshold, status, as_of, detail}.

status ∈ green|amber|red|null. null = липсва източник (principle 3: НИКОГА тих 0).
Сигналите следват spec-а; праговете са provisional (config), калибрират се с бектест.
"""
from __future__ import annotations

import datetime as _dt

from .common import percentile_rank, zscore

_SEV = {"green": 0, "amber": 1, "red": 2, "null": None}


def severity(status: str) -> int | None:
    return _SEV[status]


def _lamp(idx: int, name: str, status: str, as_of, value=None, **extra) -> dict:
    return {"id": idx, "name": name, "status": status, "value": value,
            "as_of": as_of, **extra}


# --------------------------------------------------------------------------- #
# Лампа 1 — банково репо (Adler теза): пробив на структурата от 13с дъна
# --------------------------------------------------------------------------- #
def lamp1_bank_repo(obs: list[dict]) -> dict:
    """obs = FRED H8B3092NCBA desc. Ниско/пробив надолу = репо кредитът пресъхва."""
    series = [o for o in obs if o["value"] is not None]
    if not series:
        return _lamp(1, "Банково репо (Adler)", "null", None,
                     detail="няма данни от H.8")
    cur = series[0]
    vals_desc = [o["value"] for o in series]
    pr = percentile_rank(cur["value"], vals_desc[:52], "52w")
    # 13-седмично дъно ПРЕДИ последните 13 седмици → структурен пробив надолу
    prior_trough = min(vals_desc[13:26]) if len(vals_desc) >= 26 else None
    structure_break = prior_trough is not None and cur["value"] < prior_trough
    p = pr["percentile"]
    if structure_break or (p is not None and p < 10):
        status = "red"
    elif p is not None and p < 25:
        status = "amber"
    else:
        status = "green"
    return _lamp(1, "Банково репо (Adler)", status, cur["date"],
                 value=cur["value"], percentile=pr,
                 detail={"structure_break_13w": structure_break,
                         "prior_13w_trough": prior_trough})


# --------------------------------------------------------------------------- #
# Лампа 2 — Fed plumbing: резерви vs под + SRF/repo take-up (QE-осъзнато)
#
# Калибрация gate-3 (2026-06-22):
#  · SRF/repo (FRED RPONTSYD = overnight repo, Treasury collateral) ВЕЧЕ в статуса —
#    31.10.2025=29.4 (не-QE) → red (заглавният епизод; преди беше невидим). QE барът
#    вдигнат (сезонно разкрасяване: юни-30=11, дек-31=31.5). Прагове от config.
#  · ON RRP демотиран в КОНТЕКСТ — структурно ≈0 сега ($2млрд), auto-amber палеше вечно.
#  · Резервен под = абсолютен (решение Цветослав), ранно-предупредителен буфер над LCLoR.
# --------------------------------------------------------------------------- #
def _is_quarter_end(date_str: str | None) -> bool:
    """±дни около тримесечна граница (мар/юни/сеп/дек край или нач. на следващия)."""
    if not date_str or len(date_str) < 10:
        return False
    m, d = int(date_str[5:7]), int(date_str[8:10])
    return (m in (3, 6, 9, 12) and d >= 28) or (m in (4, 7, 10, 1) and d <= 2)


def lamp2_plumbing(reserves_obs, rrp_obs, srf, thresholds) -> dict:
    res = next((o for o in reserves_obs if o["value"] is not None), None)
    rrp = next((o for o in rrp_obs if o["value"] is not None), None)
    if res is None:
        return _lamp(2, "Fed plumbing", "null", None, detail="няма WRESBAL")
    reserves_tn = res["value"] / 1e6  # WRESBAL е в $млн → $трлн
    floor = thresholds["lamp2_reserve_floor_usd_tn"]
    rrp_bn = rrp["value"] if rrp else None  # RRPONTSYD е в $млрд

    # --- резервна страна (абсолютен под) ---
    if reserves_tn < floor["red"]:
        res_status = "red"
    elif reserves_tn < floor["amber"]:
        res_status = "amber"
    else:
        res_status = "green"

    # --- SRF/repo страна (QE-осъзнато), прагове от config ---
    srf_val = srf.get("value") if isinstance(srf, dict) else srf
    srf_date = srf.get("date") if isinstance(srf, dict) else None
    qe = _is_quarter_end(srf_date)
    srf_th = thresholds.get("lamp2_srf_repo_usd_bn")
    srf_status = None
    if srf_val is not None and srf_th is not None:
        band = srf_th["qe"] if qe else srf_th["nonqe"]
        if srf_val >= band["red"]:
            srf_status = "red"
        elif srf_val >= band["amber"]:
            srf_status = "amber"
        else:
            srf_status = "green"

    # --- статус = по-лошото от {резерви, SRF} ---
    _ord = {"green": 0, "amber": 1, "red": 2}
    cands = [res_status] + ([srf_status] if srf_status is not None else [])
    status = max(cands, key=lambda s: _ord[s])

    buffer_exhausted = rrp_bn is not None and rrp_bn < 50
    return _lamp(2, "Fed plumbing", status, res["date"],
                 value=round(reserves_tn, 3),
                 detail={"reserves_usd_tn": round(reserves_tn, 3),
                         "reserves_status": res_status,
                         "floor_amber_red": [floor["amber"], floor["red"]],
                         "srf_repo_usd_bn": srf_val,            # null = няма данни, НЕ 0
                         "srf_status": srf_status,
                         "srf_quarter_end": qe,
                         "srf_note": "RPONTSYD (overnight repo, Treasury collateral) = "
                                     "SRF take-up прокси" if srf_val is not None
                                     else "няма SRF данни",
                         "on_rrp_usd_bn": rrp_bn,               # контекст, не тригер
                         "on_rrp_context": "буферът изчерпан (<$50млрд)"
                                           if buffer_exhausted else None})


# --------------------------------------------------------------------------- #
# Лампа 3 — цена на парите: SOFR−IORB + разширяване на опашката (p99 vs медиана)
# --------------------------------------------------------------------------- #
def lamp3_sofr(sofr: dict, iorb_obs, thresholds, sofr_hist=None) -> dict:
    if sofr is None:
        return _lamp(3, "Цена на парите (SOFR)", "null", None, detail="няма SOFR")
    iorb = next((o for o in iorb_obs if o["value"] is not None), None)
    iorb_v = iorb["value"] if iorb else None
    spread_bp = round((sofr["rate"] - iorb_v) * 100, 1) if iorb_v is not None else None
    # опашка: p99 − p25 (горната опашка спрямо тялото), в bp
    tail_bp = None
    if sofr["p99"] is not None and sofr["p25"] is not None:
        tail_bp = round((sofr["p99"] - sofr["p25"]) * 100, 1)
    # Калибрация gate-3 (2026-06-22): спред≥0 палеше 24.5% (49% в текущ режим) → затегнат.
    # Опашка (p99−p25) тих независим детектор (норма ~10-12bp, 2019→400bp).
    th = thresholds["lamp3_sofr_iorb_bp"]
    sp_th, tl_th = th["spread"], th["tail"]
    roll_cfg = th.get("rolling")
    _ord = {"green": 0, "amber": 1, "red": 2}

    def _band(v, t):
        if v is None:
            return None
        return "red" if v >= t["red"] else ("amber" if v >= t["amber"] else "green")

    # v1.1 устойчивост: N-дн среден спред — амбер иска УСТОЙЧИВОСТ, не единичен месечен тик.
    # red остава остър единичен (репо blowout = реагирай веднага, напр. 17.09.2019).
    rolling_bp = None
    if sofr_hist and iorb_v is not None and roll_cfg:
        vals = [o["value"] for o in sofr_hist if o.get("value") is not None][:roll_cfg["days"]]
        if len(vals) >= roll_cfg["days"]:
            rolling_bp = round((sum(vals) / len(vals) - iorb_v) * 100, 1)
    rolling_status = _band(rolling_bp, roll_cfg) if (rolling_bp is not None and roll_cfg) else None

    spread_status = _band(spread_bp, sp_th)
    tail_status = _band(tail_bp, tl_th)
    if spread_status is None and tail_status is None:
        status = "null"
    elif "red" in (spread_status, tail_status, rolling_status):
        status = "red"
    else:
        # амбер: УСТОЙЧИВ спред (rolling) ИЛИ опашка. Без rolling → fallback на единичния спред.
        amber_spread = rolling_status == "amber" if rolling_status is not None \
            else spread_status == "amber"
        status = "amber" if (amber_spread or tail_status == "amber") else "green"
    return _lamp(3, "Цена на парите (SOFR)", status, sofr["date"],
                 value=sofr["rate"],
                 detail={"sofr": sofr["rate"], "iorb": iorb_v,
                         "sofr_minus_iorb_bp": spread_bp,
                         "spread_status": spread_status,
                         "rolling_spread_bp": rolling_bp,        # v1.1 устойчивост
                         "rolling_status": rolling_status,
                         "tail_p99_minus_p25_bp": tail_bp,
                         "tail_status": tail_status,
                         "percentiles": {"p1": sofr["p1"], "p25": sofr["p25"],
                                         "p75": sofr["p75"], "p99": sofr["p99"]},
                         "volume_bn": sofr["volume_bn"]})


# --------------------------------------------------------------------------- #
# Лампа 4 — аукциони: КУПУВАЧКА СТАЧКА (broad demand failure), не репо-водопровод.
#
# Калибрация gate-3 (2026-06-22): bid-to-cover има ~нулева сила за funding-водопровод
# (септ 2019 / окт 2025 НЕ светнаха в аукционите — там стресът беше в SOFR/repo, лампи
# 2/3). База-ставка скан (534 спокойни седмици): „най-лошият единичен z≤−2" пали 15.9%
# от спокойствието → шум. Затова: само КУПОНИ (боновете = шум, 15.9% база), групирани по
# ОРИГИНАЛЕН тенор (събира reopening-ите), recency 45д, z vs последните 10 същотенорни.
# Праг по ШИРИНА: red ≥2 купона z≤−2 (база 2.4%, лови фев-2021/2018); amber ≥3 купона
# z≤−1.5 (база 1.7%). Зелена при чисти репо-епизоди — там 2/3 носят сигнала.
# --------------------------------------------------------------------------- #
_COUPON_TYPES = {"Note", "Bond"}
_L4_RECENCY_DAYS = 45
_L4_ROLL = 10
# v1.1 (2026-06-22): PD-дял тенор-релативна ос — AMBER-ОНЛИ допълнителен път.
# Растящ дял на primary dealers = другите се отдръпват, дилърът бекстопва (spec). PD-дялът
# е силно тенор-зависим (2Y mean 0.34 vs 20Y 0.14) → z спрямо СЪЩИЯ тенор, не абсолютно.
_L4_PD_ARTIFACT = 0.95   # PD-дял ≥0.95 = репортинг артефакт (SOMA add-on; PD не взима цял
                         # свръхпокрит аукцион) — филтрира се от latest И от историята
_L4_PD_Z_AMBER = 2.0     # PD-дял z праг (база 3.8%): дилърите поглъщат необичайно много
_L4_PD_BTC_GATE = 0.5    # PD-пътят брои само ако btc НЕ е силен (z≤+0.5) — иначе не е стрес
_L4_PD_BREADTH = 2       # ≥2 тенора → широк дилърски бекстоп = buyer-strike → amber


def lamp4_auctions(auctions: list[dict]) -> dict:
    coupons = [a for a in auctions
               if a.get("security_type") in _COUPON_TYPES
               and a.get("bid_to_cover") is not None and a.get("auction_date")]
    if not coupons:
        return _lamp(4, "Аукциони (купони)", "null", None,
                     detail="няма купонни аукциони (Note/Bond)")
    # детерминистична референтна дата = най-новият купонен аукцион (без datetime.now)
    ref = max(a["auction_date"] for a in coupons)
    recency_lo = (_dt.date.fromisoformat(ref)
                  - _dt.timedelta(days=_L4_RECENCY_DAYS)).isoformat()
    by_tenor: dict[str, list[dict]] = {}
    for a in coupons:
        by_tenor.setdefault(a.get("orig_term") or a["term"], []).append(a)
    evaluated = []
    for tenor, rows in by_tenor.items():
        rows.sort(key=lambda a: a["auction_date"], reverse=True)
        latest = rows[0]
        if latest["auction_date"] < recency_lo:       # няма скорошен аукцион → не брой
            continue
        hist = [r["bid_to_cover"] for r in rows[1:1 + _L4_ROLL]]
        if len(hist) < 4:
            continue
        z = zscore(latest["bid_to_cover"], hist, f"{len(hist)}/{tenor}")["z"]
        if z is None:
            continue
        # v1.1: PD-дял z (тенор-релативен), артефактите PD≥0.95 филтрирани
        pd_share = latest.get("primary_dealer_share")
        pd_z = None
        if pd_share is not None and pd_share < _L4_PD_ARTIFACT:
            pd_hist = [r["primary_dealer_share"] for r in rows[1:1 + _L4_ROLL]
                       if r.get("primary_dealer_share") is not None
                       and r["primary_dealer_share"] < _L4_PD_ARTIFACT]
            if len(pd_hist) >= 4:
                pd_z = zscore(pd_share, pd_hist, f"{len(pd_hist)}/{tenor}")["z"]
        evaluated.append({"tenor": tenor, "bid_to_cover": latest["bid_to_cover"],
                          "z": z, "auction_date": latest["auction_date"],
                          "primary_dealer_share": pd_share,
                          "pd_share_z": pd_z})
    if not evaluated:
        return _lamp(4, "Аукциони (купони)", "null", ref,
                     detail="няма скорошни купонни аукциони с достатъчно история")
    evaluated.sort(key=lambda e: e["z"])
    weak = [e for e in evaluated if e["z"] <= -1.5]
    n_weak20 = sum(1 for e in weak if e["z"] <= -2)
    # v1.1 PD-дял breadth: дилърски бекстоп (висок PD z) ПРИ не-силен btc
    pd_weak = [e for e in evaluated if e.get("pd_share_z") is not None
               and e["pd_share_z"] >= _L4_PD_Z_AMBER and e["z"] <= _L4_PD_BTC_GATE]
    n_pd_weak = len(pd_weak)
    if n_weak20 >= 2:                                   # RED = чисто bid-to-cover (непроменено)
        status = "red"
    elif len(weak) >= 3 or n_pd_weak >= _L4_PD_BREADTH:  # AMBER: btc breadth ИЛИ PD breadth
        status = "amber"
    else:
        status = "green"
    pd_amber_fired = status == "amber" and len(weak) < 3 and n_pd_weak >= _L4_PD_BREADTH
    return _lamp(4, "Аукциони (купони)", status, ref,
                 value=round(evaluated[0]["z"], 2),
                 detail={"worst_bid_to_cover_z": round(evaluated[0]["z"], 2),
                         "worst_term": evaluated[0]["tenor"],
                         "n_weak_z15": len(weak), "n_weak_z20": n_weak20,
                         "weak_tenors": weak,
                         "n_pd_weak": n_pd_weak,                  # v1.1
                         "pd_weak_tenors": pd_weak,               # v1.1
                         "pd_amber_fired": pd_amber_fired,        # v1.1 (PD сам вдигна amber)
                         "n_coupon_tenors": len(evaluated),
                         "rule": "red ≥2×btc_z≤−2 · amber ≥3×btc_z≤−1.5 ИЛИ "
                                 "≥2 тенора PD_z≥2.0 при btc_z≤0.5",
                         "method": "купони/оригинален тенор/recency45д/z-vs-roll10; PD-дял "
                                   "тенор-релативен (v1.1 amber-онли, артефакти PD≥0.95 филтр.)"})


# --------------------------------------------------------------------------- #
# Лампа 5 — ливъридж: ДВЕ оси (v1.1, 2026-06-22)
#
#  Ос-1 ОБЕМ (OFR DVP repo z, съществуваща): спад = разграждане.
#  Ос-2 ПОЗИЦИЯ (CFTC leveraged-funds нетна къса в UST фючърси): голяма/растяща =
#       натрупан basis trade; рязко падаща от зареден връх = ФОРСИРАН unwind.
#
#  Самостоятелен unwind път (решение Цветослав): позицията пали red НЕЗАВИСИМО от
#  обема. Защо — март-2020 беше точно дупката: обемът беше ВИСОК (z+2.57), та
#  обемната ос мълчеше, докато нетната къса падаше −12..−19% за 3 седмици (форсиран
#  basis unwind). 'Заредено' = нетна къса/OI (regime-robust). Unwind = 3-сед %спад
#  на нетната къса (НЕ Δpct — OI co-move-ва и маскира спада). Прагове: config.
# --------------------------------------------------------------------------- #
_L5_VOL_WINDOW = 64  # ~тримесечие дневни OFR точки (както старата лампа)


def lamp5_leverage(ofr_obs: list[dict], cftc_obs: list[dict] | None = None,
                   thresholds: dict | None = None) -> dict:
    # --- Ос-1: ОБЕМ (OFR DVP repo z) ---
    series = [o for o in ofr_obs if o["value"] is not None]
    vol_z = vol_status = vol_bn = vol_date = None
    if len(series) >= 21:
        cur = series[-1]                                  # OFR е възходящ по дата
        hist = [o["value"] for o in series[-_L5_VOL_WINDOW:-1]]
        vol_z = zscore(cur["value"], hist, "63d")["z"]
        vol_bn = round(cur["value"] / 1e9, 1)
        vol_date = cur["date"]
        vol_status = ("red" if (vol_z is not None and vol_z <= -2)
                      else "amber" if (vol_z is not None and vol_z <= -1)
                      else "green")

    # --- Ос-2: ПОЗИЦИЯ (CFTC нетна къса / OI) ---
    cf = [c for c in (cftc_obs or []) if c.get("pct_oi") is not None]
    th = (thresholds or {}).get("lamp5_cftc_leverage")
    pct_oi = ns_chg = pos_date = None
    pos_loaded = pos_moderate = unwind_red = unwind_amber = False
    has_pos = bool(cf and th)
    if has_pos:
        curp = cf[-1]
        pct_oi, pos_date = curp["pct_oi"], curp["date"]
        pos_loaded = pct_oi >= th["pct_oi_loaded"]
        pos_moderate = pct_oi >= th["pct_oi_moderate"]
        W = th["unwind_window_weeks"]
        if len(cf) > W:
            b = cf[-1 - W]                                # точка от W седмици назад
            if b.get("net_short", 0) > 0 and b.get("pct_oi") is not None \
                    and b["pct_oi"] >= th["unwind_floor_pct_oi"]:
                ns_chg = round((curp["net_short"] - b["net_short"]) / b["net_short"], 3)
                unwind_red = ns_chg <= th["unwind_3w_red"]
                unwind_amber = ns_chg <= th["unwind_3w_amber"]

    has_vol = vol_status is not None
    if not has_pos and not has_vol:
        return _lamp(5, "Ливъридж (repo+CFTC)", "null", None,
                     detail="няма нито OFR обем, нито CFTC позиция")

    # --- Комбинирай (самостоятелен unwind път) ---
    # Тиерите палят на ПРОМЯНА (unwind разпад / движещ се обем), не на стоящо състояние.
    # 'Заредена пушка' сама (голяма нетна къса) = КОНТЕКСТ, не amber — иначе става вечен
    # amber (нетна къса/OI стои 0.33-0.42 от 2024 насам), точно ON RRP уловката от Сесия 2.
    fired: list[str] = []
    context: list[str] = []
    if has_pos:
        if unwind_red:                                              # ПЪТ Б — март-2020
            status = "red"; fired.append("unwind_red")
        elif has_vol and vol_status == "red" and pos_moderate:     # ПЪТ А — двете оси
            status = "red"; fired.append("vol_collapse+loaded")
        elif has_vol and vol_status == "amber" and pos_loaded:
            status = "red"; fired.append("vol_drop+loaded_gun")
        elif unwind_amber:                                         # позицията започва да се обръща
            status = "amber"; fired.append("unwind_amber")
        elif has_vol and vol_status in ("red", "amber"):          # обем сам = частичен (мандат)
            status = "amber"; fired.append("vol_only_partial")
        else:
            status = "green"
        if pos_loaded and status == "green":                      # заредена, но не се разпада
            context.append("loaded_gun")                          # → контекст (видим), не вечен amber
    else:                                                          # CFTC недостъпна → не регресирай
        status = vol_status
        if vol_status in ("red", "amber"):
            fired.append("vol_only_legacy(pos_unavail)")

    return _lamp(5, "Ливъридж (repo+CFTC)", status, pos_date or vol_date,
                 value=vol_bn,
                 detail={
                     "volume_axis": {"dvp_repo_usd_bn": vol_bn, "volume_z_63d": vol_z,
                                     "status": vol_status, "as_of": vol_date},
                     "position_axis": {"net_short_pct_oi": pct_oi,
                                       "net_short_3w_chg": ns_chg,
                                       "loaded": pos_loaded, "moderate": pos_moderate,
                                       "unwind_red": unwind_red, "unwind_amber": unwind_amber,
                                       "as_of": pos_date,
                                       "source": "CFTC TFF Leveraged Funds, UST 6-code agg"},
                     "fired": fired,
                     "context": context,                # напр. loaded_gun (заредено, но не стреля)
                     "cftc_leveraged_cross": pct_oi,    # placeholder вече запълнен
                     "note": "две оси: OFR DVP обем + CFTC нетна къса; самостоятелен unwind път"})
