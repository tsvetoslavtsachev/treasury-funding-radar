"""Composite: 5 лампи → скор 0–10 + категорична присъда на български.

null лампи (липсва източник) се ИЗКЛЮЧВАТ от знаменателя и се изброяват явно —
никога не броим липсващ източник като 0/зелено (principle 3).

Изходни полета (в допълнение към score/verdict/reds/ambers/null_lamps):
  · low_confidence (Ф1b) — True при ≤2 активни лампи; изходният слой го показва като
    „(малка извадка активни лампи)". Малък знаменател → 1 red пали 10.0 без уговорка.
  · clusters (Ф3) — ако L2 И L3 палят red едновременно, маркира „L2+L3 = репо клъстер
    (един сигнал)": двете гледат СЪЩИЯ overnight repo пазар → 2 гласа за 1 епизод.
Присъдата НЕ мълчи при amber в „Спокойно" бандата (Ф1a): при ≥1 amber заглавието става
„Спокойно, с наблюдение по L<id>" (UI легендата казва amber=„наблюдение").
Числената скала НЕ се пипа — само етикети/полета.
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
                "reds": [], "ambers": [], "low_confidence": True, "clusters": []}
    raw = sum(s for _, s in active)
    score = round(10.0 * raw / (2 * len(active)), 1)
    reds = [l["id"] for l, s in active if s == 2]
    ambers = [l["id"] for l, s in active if s == 1]

    verdict = verdict_for(score)
    # Ф1a: amber в „Спокойно" бандата (≤1.0) → заглавието да не мълчи; числената скала стои.
    if score <= _BANDS[0][0] and ambers:
        verdict = "Спокойно, с наблюдение по " + ", ".join(f"L{i}" for i in ambers)

    # Ф3: L2+L3 = един overnight repo пазар (цена SOFR−IORB + количество резерви/SRF).
    # При двойно red палене броим 2 гласа за 1 епизод → маркирай като клъстер (само етикет).
    clusters = []
    if 2 in reds and 3 in reds:
        clusters.append("L2+L3 = репо клъстер (един сигнал)")

    return {
        "score": score,
        "verdict": verdict,
        "n_active": len(active),
        "null_lamps": null_lamps,                       # явно, не скрито
        "reds": reds,
        "ambers": ambers,
        "low_confidence": len(active) <= 2,             # Ф1b: малък знаменател → уговорка
        "clusters": clusters,                           # Ф3: репо-клъстер етикет
    }
