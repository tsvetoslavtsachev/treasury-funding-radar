"""Офлайн детерминистичен тест на ядрото (нула мрежа).

Покрива логиката, не fetcher-ите: identity guard · window-етикети · лампи статуси ·
composite скалиране + null-изключване. Runnable без pytest: `python tests/test_core.py`.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from funding_radar.common import assert_keys, percentile_rank, zscore, FetchError
from funding_radar.composite import composite, verdict_for
from funding_radar import lamps as L


def test_identity_guard_raises_on_drift():
    assert_keys({"a": 1, "b": 2}, ["a", "b"], "ok")          # no raise
    try:
        assert_keys({"a": 1}, ["a", "b"], "drift")
    except FetchError as e:
        assert "schema drift" in str(e) and "b" in str(e)
    else:
        raise AssertionError("очаквах FetchError при липсващ ключ")


def test_window_labels_carried():
    pr = percentile_rank(5, [1, 2, 3, 4, 5], "52w")
    assert pr["window"] == "52w" and pr["n"] == 5 and pr["percentile"] == 100.0
    z = zscore(10, [1, 2, 3], "3w")
    assert z["window"] == "3w" and z["z"] is not None


def test_percentile_empty_history_null_not_zero():
    pr = percentile_rank(5, [], "52w")
    assert pr["percentile"] is None and pr["n"] == 0     # null, не 0 (principle 3)


def test_verdict_bands():
    assert verdict_for(0.5) == "Спокойно финансиране"
    assert verdict_for(3.0) == "Леко напрежение"
    assert verdict_for(6.0) == "Повишено наблюдение"
    assert verdict_for(10.0) == "Остър funding стрес"


def test_composite_excludes_null_from_denominator():
    lamps = [
        {"id": 1, "status": "green"}, {"id": 2, "status": "red"},
        {"id": 3, "status": "null"},                       # липсва източник
    ]
    c = composite(lamps)
    assert c["n_active"] == 2 and c["null_lamps"] == [3]
    # raw = 0+2 = 2; scale 10*2/(2*2) = 5.0
    assert c["score"] == 5.0 and c["reds"] == [2]


def test_composite_all_null_is_no_data():
    c = composite([{"id": 1, "status": "null"}, {"id": 2, "status": "null"}])
    assert c["score"] is None and c["verdict"] == "Няма данни"


def test_lamp_null_when_source_empty():
    assert L.lamp1_bank_repo([])["status"] == "null"
    assert L.lamp3_sofr(None, [], {"lamp3_sofr_iorb_bp": {"amber": 0, "red": 5}})["status"] == "null"
    assert L.lamp4_auctions([])["status"] == "null"


_TH3 = {"lamp3_sofr_iorb_bp": {"spread": {"amber": 5, "red": 15},
                               "tail": {"amber": 25, "red": 50},
                               "rolling": {"days": 5, "amber": 5, "red": 10}}}


def test_lamp3_rolling_suppresses_single_day_spike():
    # единичен +7bp ден, но 5-дн среден е нисък → НЕ амбер (устойчивост, v1.1)
    sofr = {"date": "2026-06-30", "rate": 3.72, "p1": 3.66, "p25": 3.68,
            "p75": 3.74, "p99": 3.78, "volume_bn": 3000}
    iorb = [{"date": "2026-06-30", "value": 3.65}]              # спред +7bp единичен
    hist = [{"date": "2026-06-30", "value": 3.72}] + \
           [{"date": f"2026-06-2{i}", "value": 3.60} for i in range(5)]  # среден ~ -2.6bp
    out = L.lamp3_sofr(sofr, iorb, _TH3, sofr_hist=hist)
    assert out["detail"]["sofr_minus_iorb_bp"] == 7.0           # единичният +7 си личи
    assert out["detail"]["rolling_status"] == "green" and out["status"] == "green"


def test_lamp3_spread_green_when_below_iorb():
    sofr = {"date": "2026-06-18", "rate": 3.62, "p1": 3.58, "p25": 3.60,
            "p75": 3.67, "p99": 3.70, "volume_bn": 3148}
    out = L.lamp3_sofr(sofr, [{"date": "2026-06-22", "value": 3.65}], _TH3)
    assert out["status"] == "green"                        # спред -3bp, опашка 10bp
    assert out["detail"]["sofr_minus_iorb_bp"] == -3.0


def test_lamp3_small_positive_spread_no_longer_ambers():
    # спред +3bp (под стария amber@0 палеше) — затегнат на +5 → зелено
    sofr = {"date": "2026-06-18", "rate": 3.68, "p1": 3.60, "p25": 3.62,
            "p75": 3.70, "p99": 3.72, "volume_bn": 3000}
    out = L.lamp3_sofr(sofr, [{"date": "2026-06-18", "value": 3.65}], _TH3)
    assert out["detail"]["sofr_minus_iorb_bp"] == 3.0 and out["status"] == "green"


def test_lamp3_tail_widening_fires_red_alone():
    # спред зелен (-3bp), но опашката се разтваря (60bp) → red през опашката
    sofr = {"date": "2019-09-17", "rate": 3.62, "p1": 3.55, "p25": 3.60,
            "p75": 3.90, "p99": 4.20, "volume_bn": 1000}
    out = L.lamp3_sofr(sofr, [{"date": "2019-09-17", "value": 3.65}], _TH3)
    assert out["detail"]["tail_p99_minus_p25_bp"] == 60.0
    assert out["detail"]["tail_status"] == "red" and out["status"] == "red"


_TH2 = {
    "lamp2_reserve_floor_usd_tn": {"amber": 3.0, "red": 2.8},
    "lamp2_srf_repo_usd_bn": {"nonqe": {"amber": 5.0, "red": 20.0},
                              "qe": {"amber": 15.0, "red": 30.0}},
}


def test_lamp2_srf_nonqe_red():
    # резерви над пода (зелено), но SRF/repo 29.4 на не-QE ден → red (еталон 31.10.2025)
    out = L.lamp2_plumbing([{"date": "2025-10-31", "value": 3033000.0}],
                           [{"date": "2025-10-31", "value": 0.001}],
                           {"value": 29.4, "date": "2025-10-31"}, _TH2)
    assert out["status"] == "red" and out["detail"]["srf_status"] == "red"
    assert out["detail"]["srf_quarter_end"] is False


def test_lamp2_srf_quarter_end_suppressed():
    # SRF 11 на quarter-end (юни-30) = сезонно → НЕ пали (QE барът е 15/30)
    out = L.lamp2_plumbing([{"date": "2025-06-30", "value": 3300000.0}],
                           [{"date": "2025-06-30", "value": 200.0}],
                           {"value": 11.0, "date": "2025-06-30"}, _TH2)
    assert out["detail"]["srf_quarter_end"] is True
    assert out["detail"]["srf_status"] == "green" and out["status"] == "green"


def test_lamp2_rrp_demoted_to_context():
    # ON RRP източен вече НЕ пали amber сам (демотиран в контекст)
    out = L.lamp2_plumbing([{"date": "2026-06-17", "value": 3033000.0}],
                           [{"date": "2026-06-17", "value": 0.001}],
                           {"value": 0.0, "date": "2026-06-17"}, _TH2)
    assert out["status"] == "green"
    assert out["detail"]["on_rrp_context"] == "буферът изчерпан (<$50млрд)"


# --------------------------------------------------------------------------- #
# Лампа 5 — две оси (обем OFR + позиция CFTC), v1.1
# --------------------------------------------------------------------------- #
_TH5 = {"lamp5_cftc_leverage": {
    "pct_oi_loaded": 0.33, "pct_oi_moderate": 0.25, "unwind_window_weeks": 3,
    "unwind_floor_pct_oi": 0.15, "unwind_3w_amber": -0.08, "unwind_3w_red": -0.12}}


def _cftc(points):
    """points = [(net_short, oi), …] ascending → lamp вход с pct_oi."""
    return [{"date": f"2020-03-{i:02d}", "net_short": ns, "oi": oi,
             "pct_oi": round(ns / oi, 4)} for i, (ns, oi) in enumerate(points, 1)]


def _ofr(cur_value):
    """41 точки: 40 редуващи се около 3000e9 (sd≈50e9) + 1 текуща = cur_value."""
    hist = [{"date": f"d{i}", "value": 3000e9 + (50e9 if i % 2 else -50e9)} for i in range(40)]
    return hist + [{"date": "cur", "value": cur_value}]


def test_lamp5_unwind_red_overrides_benign_volume():
    # ГЛАВНИЯТ тест (март-2020 дупката): нетна къса пада −15% за 3 седмици от зареден
    # връх, а обемът е ВИСОК/спокоен (z~0) → позицията пали red САМА.
    cftc = _cftc([(3_600_000, 16_363_636),   # cf[-4] база: pct 0.22
                  (3_400_000, 16_000_000),
                  (3_200_000, 15_600_000),
                  (3_060_000, 15_300_000)])   # cf[-1] текуща: pct 0.20, 3w%chg −0.15
    out = L.lamp5_leverage(_ofr(3000e9), cftc, _TH5)   # обем спокоен (z~0, green)
    assert out["status"] == "red", out["detail"]
    assert "unwind_red" in out["detail"]["fired"]
    assert out["detail"]["volume_axis"]["status"] == "green"  # обемната ос мълчи — точно дупката


def test_lamp5_loaded_gun_is_context_not_eternal_amber():
    # Голяма нетна къса (pct 0.40), без unwind, спокоен обем → ЗЕЛЕНО + context loaded_gun.
    # (Демотирано от amber: нетна къса/OI стои висока с години → вечен amber = ON RRP уловката.)
    cftc = _cftc([(4_800_000, 12_000_000)] * 4)        # pct 0.40 плосък
    out = L.lamp5_leverage(_ofr(3000e9), cftc, _TH5)
    assert out["status"] == "green"
    assert "loaded_gun" in out["detail"]["context"]
    assert out["detail"]["position_axis"]["loaded"] is True


def test_lamp5_volume_collapse_plus_loaded_is_red():
    # Обемен колапс (z≤−2) ПРИ умерено зареден (pct 0.30 ≥ 0.25) → red (двете оси, път А)
    cftc = _cftc([(4_800_000, 16_000_000)] * 4)        # pct 0.30 плосък (moderate, не loaded)
    out = L.lamp5_leverage(_ofr(2700e9), cftc, _TH5)   # обемен спад z≈−6
    assert out["status"] == "red" and "vol_collapse+loaded" in out["detail"]["fired"]


def test_lamp5_volume_drop_alone_is_partial_amber():
    # Обемен спад САМ (pct ниско 0.10, без unwind) → amber, НЕ red (обем сам = частичен)
    cftc = _cftc([(1_600_000, 16_000_000)] * 4)        # pct 0.10
    out = L.lamp5_leverage(_ofr(2700e9), cftc, _TH5)
    assert out["status"] == "amber" and "vol_only_partial" in out["detail"]["fired"]


def test_lamp5_benign_both_green():
    cftc = _cftc([(1_600_000, 16_000_000)] * 4)        # pct 0.10 плосък
    out = L.lamp5_leverage(_ofr(3000e9), cftc, _TH5)   # обем z~0
    assert out["status"] == "green" and out["detail"]["fired"] == []


def test_lamp5_cftc_absent_keeps_legacy_volume_red():
    # CFTC недостъпна → НЕ регресирай: legacy обемен z≤−2 остава red
    out = L.lamp5_leverage(_ofr(2700e9), None, _TH5)
    assert out["status"] == "red" and "vol_only_legacy(pos_unavail)" in out["detail"]["fired"]


def test_lamp5_both_sources_null():
    assert L.lamp5_leverage([], [], _TH5)["status"] == "null"


# --------------------------------------------------------------------------- #
# Лампа 4 — PD-дял тенор-релативна ос (v1.1, amber-онли)
# --------------------------------------------------------------------------- #
def _l4_auc(term, date, btc, pd):
    return {"security_type": "Note", "auction_date": date, "term": term,
            "orig_term": term, "bid_to_cover": btc, "primary_dealer_share": pd}


def _l4_tenor(term, btc_hist, pd_hist, btc_latest, pd_latest):
    dates = ["2026-01-12", "2026-02-12", "2026-03-12", "2026-04-12", "2026-05-12"]
    aucs = [_l4_auc(term, d, b, p) for d, b, p in zip(dates, btc_hist, pd_hist)]
    aucs.append(_l4_auc(term, "2026-06-12", btc_latest, pd_latest))  # latest (в recency)
    return aucs


_BH = [2.48, 2.52, 2.48, 2.52, 2.50]   # btc история (mean 2.50, sd~0.02)
_PH = [0.18, 0.22, 0.18, 0.22, 0.20]   # PD-дял история (mean 0.20, sd~0.02)


def test_lamp4_pd_amber_fires_on_broad_dealer_backstop():
    # 2 тенора: PD скача 0.20→0.40 (z~+10), btc плосък (z~0) → amber през PD пътя
    aucs = _l4_tenor("5-Year", _BH, _PH, 2.50, 0.40) + _l4_tenor("7-Year", _BH, _PH, 2.50, 0.40)
    out = L.lamp4_auctions(aucs)
    assert out["status"] == "amber"
    assert out["detail"]["n_pd_weak"] == 2 and out["detail"]["pd_amber_fired"] is True
    assert out["detail"]["n_weak_z15"] == 0           # btc не е слаб — amber-ът е чисто PD


def test_lamp4_pd_artifact_filtered():
    # latest PD=1.00 (артефакт) → филтриран → само 1 легитимен PD-weak → НЕ amber
    aucs = _l4_tenor("5-Year", _BH, _PH, 2.50, 1.00) + _l4_tenor("7-Year", _BH, _PH, 2.50, 0.40)
    out = L.lamp4_auctions(aucs)
    assert out["detail"]["n_pd_weak"] == 1 and out["status"] == "green"


def test_lamp4_pd_path_gated_by_strong_btc():
    # PD скача в 2 тенора, НО btc е силен (z≫+0.5) → не е стрес → green
    bh = [2.30, 2.34, 2.30, 2.34, 2.32]
    aucs = _l4_tenor("5-Year", bh, _PH, 2.80, 0.40) + _l4_tenor("7-Year", bh, _PH, 2.80, 0.40)
    out = L.lamp4_auctions(aucs)
    assert out["detail"]["n_pd_weak"] == 0 and out["status"] == "green"


def test_lamp4_pd_does_not_regress_btc_red():
    # btc срив в 2 тенора (z≤−2) → red, независимо от PD (red = чисто bid-to-cover)
    aucs = _l4_tenor("5-Year", _BH, _PH, 2.20, 0.20) + _l4_tenor("7-Year", _BH, _PH, 2.20, 0.20)
    out = L.lamp4_auctions(aucs)
    assert out["status"] == "red"


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(_run())
