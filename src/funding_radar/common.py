"""HTTP + health + identity guard + window-labeled статистики.

Target принципи (Фаза-2 съответствие, от spec):
1. Identity guard — серия пинната по ID; schema assert при fetch.
2. health.json per source — status/as_of/error всеки run.
3. No silent zero — счупен източник = null + badge, никога 0.
4. Window етикети — всеки percentile/z носи прозореца си.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class FetchError(Exception):
    """Мрежова/HTTP/parse грешка — носи се до health записа, не се поглъща тихо."""


def http_get_json(url: str, *, timeout: int = 25, retries: int = 2,
                  backoff: float = 1.5) -> Any:
    """GET → parsed JSON. Декомпресира gzip. Retry на 429/5xx/timeout.

    Хвърля FetchError при изчерпани опити — викащият го записва в health (no silent 0).
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "treasury-funding-radar/0.1 (+INIT-22)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff ** attempt)
                continue
            raise FetchError(f"HTTP {e.code} @ {url}") from e
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
                continue
            raise FetchError(f"{type(e).__name__} @ {url}: {e}") from e
    raise FetchError(f"exhausted @ {url}: {last}")


def assert_keys(obj: dict, keys: list[str], where: str) -> None:
    """Identity/schema guard — отказва тихата дрейф на схемата на източника."""
    missing = [k for k in keys if k not in obj]
    if missing:
        raise FetchError(f"schema drift @ {where}: missing {missing}")


# --------------------------------------------------------------------------- #
# Health (principle 2)
# --------------------------------------------------------------------------- #
@dataclass
class SourceHealth:
    source: str
    status: str = "unknown"          # ok | stale | error | missing
    as_of: str | None = None         # ISO дата на последната стойност
    error: str | None = None


@dataclass
class HealthBook:
    sources: dict[str, SourceHealth] = field(default_factory=dict)

    def ok(self, source: str, as_of: str | None) -> None:
        self.sources[source] = SourceHealth(source, "ok", as_of, None)

    def error(self, source: str, msg: str) -> None:
        self.sources[source] = SourceHealth(source, "error", None, msg)

    def missing(self, source: str, msg: str) -> None:
        self.sources[source] = SourceHealth(source, "missing", None, msg)

    def any_dead(self) -> bool:
        return any(s.status in ("error", "missing") for s in self.sources.values())

    def to_dict(self) -> dict:
        return {
            "any_dead": self.any_dead(),
            "sources": {k: asdict(v) for k, v in self.sources.items()},
        }


# --------------------------------------------------------------------------- #
# Window-labeled статистики (principle 4)
# --------------------------------------------------------------------------- #
def percentile_rank(value: float, history: list[float], window_label: str) -> dict:
    """Перцентилен ранг на value в history. Връща стойност + ЕТИКЕТ на прозореца."""
    hist = [h for h in history if h is not None]
    if not hist:
        return {"percentile": None, "window": window_label, "n": 0}
    below = sum(1 for h in hist if h <= value)
    return {
        "percentile": round(100.0 * below / len(hist), 1),
        "window": window_label,
        "n": len(hist),
    }


def zscore(value: float, history: list[float], window_label: str) -> dict:
    """Z-score спрямо history с етикет на прозореца."""
    hist = [h for h in history if h is not None]
    if len(hist) < 2:
        return {"z": None, "window": window_label, "n": len(hist)}
    mean = sum(hist) / len(hist)
    var = sum((h - mean) ** 2 for h in hist) / (len(hist) - 1)
    sd = var ** 0.5
    z = (value - mean) / sd if sd > 0 else 0.0
    return {"z": round(z, 2), "window": window_label, "n": len(hist)}
