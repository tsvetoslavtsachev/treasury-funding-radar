"""Историята на лампите по дни: data/lamps_history.csv (ПРОЛЕТР2, 25.11.2026).

Един ред = една лампа в един ден. Колоните:
  date    денят на точката в историята (UTC денят на пуска; при дописване денят, за
          който е сметнато)
  lamp    1..5
  name    името на лампата, както в lamps.json
  status  green | amber | red | null (null = сиво: липсва или старо, с причина в note)
  value   стойността на лампата, както в lamps.json
  as_of   датата на последната точка в източника на лампата (за лампа 4: последният
          купонен аукцион с резултат)
  kind    жив       = записан от пуска на радара в този ден
          дописан   = сметнат по-късно от източниците със същите функции (backfill.py),
                      с данните, публикувани към този ден (FRED по ALFRED)
  note    причината за сивото, ако има

Правила: ред „жив“ не се презаписва от „дописан“; при няколко живи пуска в един ден
остава последният. Файлът е подреден по (date, lamp) и се пише с LF.
"""
from __future__ import annotations

import csv
import io
import pathlib

FIELDS = ["date", "lamp", "name", "status", "value", "as_of", "kind", "note"]
LIVE, BACKFILL = "жив", "дописан"


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(round(v, 6))
    return str(v)


def rows_from_lamps(lamps: list[dict], day: str, kind: str) -> list[dict]:
    """Петте лампи на един пуск → редове за историята (стойностите като текст)."""
    out = []
    for l in lamps:
        note = (l.get("stale") or {}).get("reason") or ""
        if not note and l.get("status") == "null" and isinstance(l.get("detail"), str):
            note = l["detail"]
        out.append({"date": day, "lamp": str(l["id"]), "name": l["name"],
                    "status": l["status"], "value": _fmt(l.get("value")),
                    "as_of": _fmt(l.get("as_of")), "kind": kind, "note": note})
    return out


def load(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    """Слива по (date, lamp). Живият ред печели срещу дописан; нов жив сменя стар жив;
    нов дописан сменя само стар дописан."""
    by = {(r["date"], r["lamp"]): r for r in existing}
    for r in new:
        k = (r["date"], r["lamp"])
        old = by.get(k)
        if old is None or r["kind"] == LIVE or old["kind"] == BACKFILL:
            by[k] = r
    return [by[k] for k in sorted(by, key=lambda k: (k[0], int(k[1])))]


def dumps(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in FIELDS})
    return buf.getvalue()


def write(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(dumps(rows))


def update(path: pathlib.Path, lamps: list[dict], day: str, kind: str = LIVE) -> int:
    """Добавя (или сменя) редовете на един ден. Връща броя редове във файла."""
    rows = merge(load(path), rows_from_lamps(lamps, day, kind))
    write(path, rows)
    return len(rows)
