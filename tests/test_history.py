"""Историята на лампите и дописването назад (ПРОЛЕТР2, 25.11.2026). Без мрежа."""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from funding_radar import history as Hs
from funding_radar import backfill as B


def _lamps(v1=1.0, st4="green"):
    return [{"id": 1, "name": "Банково репо", "status": "green", "value": v1, "as_of": "2026-11-04"},
            {"id": 4, "name": "Аукциони (купони)", "status": st4, "value": -2.49, "as_of": "2026-10-08",
             **({"stale": {"reason": "няма купонен аукцион с резултат след 2026-10-08"}}
                if st4 == "null" else {})}]


def test_live_beats_backfill_and_last_live_wins():
    back = Hs.rows_from_lamps(_lamps(1.0), "2026-11-20", Hs.BACKFILL)
    live1 = Hs.rows_from_lamps(_lamps(2.0), "2026-11-20", Hs.LIVE)
    live2 = Hs.rows_from_lamps(_lamps(3.0), "2026-11-20", Hs.LIVE)
    rows = Hs.merge(Hs.merge(Hs.merge([], live1), back), live2)
    r1 = [r for r in rows if r["lamp"] == "1"]
    assert len(r1) == 1 and r1[0]["value"] == "3.0" and r1[0]["kind"] == Hs.LIVE


def test_backfill_replaces_only_backfill():
    a = Hs.rows_from_lamps(_lamps(1.0), "2026-11-19", Hs.BACKFILL)
    b = Hs.rows_from_lamps(_lamps(5.0), "2026-11-19", Hs.BACKFILL)
    rows = Hs.merge(a, b)
    assert [r["value"] for r in rows if r["lamp"] == "1"] == ["5.0"]


def test_grey_carries_reason_and_csv_roundtrip(tmp_path):
    p = tmp_path / "h.csv"
    Hs.update(p, _lamps(st4="null"), "2026-11-25")
    rows = Hs.load(p)
    r4 = [r for r in rows if r["lamp"] == "4"][0]
    assert r4["status"] == "null" and "2026-10-08" in r4["note"] and r4["as_of"] == "2026-10-08"
    assert b"\r\n" not in p.read_bytes()


def test_fred_asof_uses_vintage_known_before_day():
    # H8B3092NCBA: 04.11 е 833078,2 в реколтата 13.11-19.11 и 832996 от 20.11 (ALFRED)
    vint = [{"date": "2026-11-04", "rs": "2026-11-13", "re": "2026-11-19", "value": 833078.2},
            {"date": "2026-11-04", "rs": "2026-11-20", "re": "9999-12-31", "value": 832996.0},
            {"date": "2026-11-11", "rs": "2026-11-20", "re": "9999-12-31", "value": 817679.9}]
    assert B.fred_asof(vint, "2026-11-19")[0] == {"date": "2026-11-04", "value": 833078.2}
    assert B.fred_asof(vint, "2026-11-22")[0] == {"date": "2026-11-11", "value": 817679.9}


def test_business_day_lag():
    assert B._minus_bd("2026-11-23", 2) == "2026-11-19"   # понеделник → четвъртък
    assert B._minus_bd("2026-11-20", 2) == "2026-11-18"


def test_unit_change_between_vintages():
    units = [("2024-11-20", "2025-11-12", "Billions of U.S. Dollars"),
             ("2025-11-13", "9999-12-31", "Millions of U.S. Dollars")]
    assert B.unit_factor(units, "2025-06-01") == 1000.0
    assert B.unit_factor(units, "2025-11-20") == 1.0
    assert B.unit_factor([("2024-11-20", "9999-12-31", "Percent")], "2025-01-01") == 1.0


# --------------------------------------------------------------------------- #
# Аукционите: целият прозорец, страница по страница, и пазач срещу рязане (25.11.2026)
# (старият четец на Fiscal Data; от 27.11.2026 остава за калибровката и сверката)
# --------------------------------------------------------------------------- #
from funding_radar import sources as S          # noqa: E402
from funding_radar.common import FetchError     # noqa: E402


def _row(i):
    return {"auction_date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "security_type": "Note",
            "security_term": "7-Year", "original_security_term": "7-Year",
            "bid_to_cover_ratio": "2.5", "primary_dealer_accepted": "10", "total_accepted": "100"}


def _fake_api(monkeypatch, n, page_size, total=None, drop_last_page=False):
    rows = [_row(i) for i in range(n)]
    pages = max(1, -(-n // page_size))
    seen = []

    def fake(url):
        num = int(url.split("page%5Bnumber%5D=")[1].split("&")[0]) if "page%5Bnumber%5D=" in url else 1
        seen.append(num)
        chunk = [] if (drop_last_page and num == pages) else rows[(num - 1) * page_size: num * page_size]
        return {"data": chunk, "meta": {"total-count": total if total is not None else n,
                                        "total-pages": pages}}
    monkeypatch.setattr(S, "http_get_json", fake)
    return seen


def test_auctions_fetch_all_pages(monkeypatch):
    seen = _fake_api(monkeypatch, n=250, page_size=100)
    out = S.fetch_auctions_fiscaldata(base="b", path="/p", since="2025-01-01", page_size=100)
    assert len(out) == 250 and seen == [1, 2, 3]


def test_auctions_truncation_is_loud(monkeypatch):
    _fake_api(monkeypatch, n=250, page_size=100, drop_last_page=True)
    try:
        S.fetch_auctions_fiscaldata(base="b", path="/p", since="2025-01-01", page_size=100)
    except FetchError as e:
        assert "отрязано" in str(e)
    else:
        raise AssertionError("рязането мина тихо")


# --------------------------------------------------------------------------- #
# ПРОЛЕТБ2 (27.11.2026): лампа 4 от TreasuryDirect, същите полета и числа като Fiscal Data
# --------------------------------------------------------------------------- #
from funding_radar import lamps as L            # noqa: E402


def _td(date, term="7-Year", btc="2.50", pd="4000000000", grand="50000000000",
        st="Note", t="Note", cusip=None, offering="44000000000", orig=None, n=3):
    return {"cusip": cusip or f"C{date}{term}", "securityType": st, "type": t,
            "securityTerm": term, "originalSecurityTerm": orig if orig is not None else term,
            "treasuryAuctionResultsXmlFileName": f"R_{date.replace('-', '')}_{n}.xml" if date else "",
            "bidToCoverRatio": btc, "primaryDealersCompetitiveParAwarded": pd,
            "grandTotalParAwarded": grand, "offeringAmount": offering,
            "inflationProtected": "Yes" if t == "TIPS" else "No",
            "floatingRate": "Yes" if t == "FRN" else "No"}


def test_td_date_from_results_file_name():
    assert S.td_auction_date(_td("2026-11-25")) == "2026-11-25"
    assert S.td_auction_date(_td(None)) is None                     # обявен, още без резултат
    try:
        S.td_auction_date({"treasuryAuctionResultsXmlFileName": "R_20261399_1.xml"})
    except FetchError:
        pass
    else:
        raise AssertionError("невалидна дата в името мина тихо")


def test_td_parse_fields_match_fiscaldata_shape():
    rows = [_td("2026-11-25", pd="4000000000", grand="50000000000"),
            _td("2026-11-24", term="2-Year", st="Note", t="FRN"),            # FRN е Note, както във FD
            _td("2026-11-19", term="10-Year", st="Note", t="TIPS"),          # TIPS също
            _td("2026-11-20", term="17-Week", st="Bill", t="Bill"),          # боновете не
            _td(None),                                                       # без резултат
            _td("2026-11-18", btc=""),                                       # празно = липса
            _td("2026-11-17", btc="null"),
            _td("2019-06-21", offering="25000000"),                          # технически ред
            _td("2024-01-02")]                                               # преди since
    out = S.parse_td_auctions(rows, since="2025-01-01")
    assert [a["auction_date"] for a in out] == ["2026-11-25", "2026-11-24", "2026-11-19"]
    a = out[0]
    assert set(a) == {"auction_date", "cusip", "security_type", "kind", "term", "orig_term",
                      "bid_to_cover", "primary_dealer_share"}
    assert [x["kind"] for x in out] == ["nominal", "FRN", "TIPS"]
    assert a["bid_to_cover"] == 2.5 and a["primary_dealer_share"] == 0.08


def test_td_missing_pd_is_none_not_zero():
    out = S.parse_td_auctions([_td("2026-11-25", pd=""), _td("2026-11-24", grand="0")],
                              since="2026-01-01")
    assert [a["primary_dealer_share"] for a in out] == [None, None]


def test_td_reopening_keeps_original_term():
    out = S.parse_td_auctions([_td("2026-11-12", term="9-Year 10-Month", orig="10-Year"),
                               _td("2026-11-13", term="10-Year", orig="")], since="2026-01-01")
    assert {a["orig_term"] for a in out} == {"10-Year"}


def test_td_fetch_asks_every_type_and_guards(monkeypatch):
    seen = []

    def fake(url, timeout=None):
        seen.append(url)
        return [_td("2026-11-25", cusip=url[-4:])]
    monkeypatch.setattr(S, "http_get_json", fake)
    out = S.fetch_auctions(base="https://x/TA_WS", path="/securities/search", since="2026-01-01")
    assert [u.split("type=")[1] for u in seen] == ["Note", "Bond", "TIPS", "FRN"]
    assert all("format=json" in u for u in seen) and len(out) == 4

    monkeypatch.setattr(S, "http_get_json", lambda url, timeout=None: [])
    try:
        S.fetch_auctions(base="b", path="/p", since="2026-01-01")
    except FetchError as e:
        assert "празен" in str(e)
    else:
        raise AssertionError("празен отговор мина тихо")

    broken = _td("2026-11-25"); del broken["grandTotalParAwarded"]
    monkeypatch.setattr(S, "http_get_json", lambda url, timeout=None: [broken])
    try:
        S.fetch_auctions(base="b", path="/p", since="2026-01-01")
    except FetchError:
        pass
    else:
        raise AssertionError("смяната на полетата мина тихо")


def test_td_rows_light_lamp4():
    """Пресни TD редове (последен 25.11) → лампата има цвят на 27.11.2026, не е сива."""
    rows = []
    for term in ("2-Year", "5-Year", "7-Year"):
        for i in range(11):
            d = (_dt.date(2026, 11, 25) - _dt.timedelta(days=30 * i)).isoformat()
            rows.append(_td(d, term=term, btc=f"{2.5 + 0.01 * (i % 3):.2f}"))
    out = L.lamp4_auctions(S.parse_td_auctions(rows, since="2025-10-23"), today="2026-11-27")
    assert out["as_of"] == "2026-11-25" and out["status"] in ("green", "amber", "red")
    assert "stale" not in out
