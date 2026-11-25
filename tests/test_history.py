"""Историята на лампите и дописването назад (ПРОЛЕТР2, 25.11.2026). Без мрежа."""
from __future__ import annotations

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
    out = S.fetch_auctions(base="b", path="/p", since="2025-01-01", page_size=100)
    assert len(out) == 250 and seen == [1, 2, 3]


def test_auctions_truncation_is_loud(monkeypatch):
    _fake_api(monkeypatch, n=250, page_size=100, drop_last_page=True)
    try:
        S.fetch_auctions(base="b", path="/p", since="2025-01-01", page_size=100)
    except FetchError as e:
        assert "отрязано" in str(e)
    else:
        raise AssertionError("рязането мина тихо")
