"""Composite: 5 лампи → скор 0–10 + категорична присъда на български.

null лампи (липсва източник) се ИЗКЛЮЧВАТ от знаменателя и се изброяват явно —
никога не броим липсващ източник като 0/зелено (principle 3).
"""
from __future__ import annotations

from .lamps import severity

# Присъдни ленти върху скалирания 0–10 скор.
_BANDS = [
    (1.0, "Спокойно финансиране"),
    (3.0, "Леко напрежение"),
    (6.0, "Повишено наблюдение"),
    (8.0, "Засилен стрес"),
    (10.0, "Остър funding стрес"),
]


def verdict_for(score: float) -> str:
    for hi, label in _BANDS:
        if score <= hi:
            return label
    return _BANDS[-1][1]


def composite(lamps: list[dict]) -> dict:
    sevs = [(l, severity(l["status"])) for l in lamps]
    active = [(l, s) for l, s in sevs if s is not None]
    null_lamps = [l["id"] for l, s in sevs if s is None]
    if not active:
        return {"score": None, "verdict": "Няма данни", "n_active": 0,
                "null_lamps": null_lamps,
                "reds": [], "ambers": []}
    raw = sum(s for _, s in active)
    score = round(10.0 * raw / (2 * len(active)), 1)
    return {
        "score": score,
        "verdict": verdict_for(score),
        "n_active": len(active),
        "null_lamps": null_lamps,                       # явно, не скрито
        "reds": [l["id"] for l, s in active if s == 2],
        "ambers": [l["id"] for l, s in active if s == 1],
    }
