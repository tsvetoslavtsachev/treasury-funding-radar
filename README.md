# Treasury Funding Radar

Зона-1 сетиво (INIT-22 S16). **Funding стрес = ранна (leading) детекция** на принудителния
избор на Фед — долар vs облигации. Лампите не предсказват посоката на активите, а
**близостта и цената на policy отговора**. Отделна предупредителна линия от ценовия VRM
Kill Switch (lagging); **БЕЗ промяна на KS правилата**.

## 5-те лампи

| # | Лампа | Източник (resolved 2026-06-22) | Сигнал |
|---|---|---|---|
| 1 | Банково репо (Adler) | FRED `H8B3092NCBA` (H.8, W) | пробив на структурата от 13-седмични дъна |
| 2 | Fed plumbing | FRED `WRESBAL` + `RRPONTSYD` (SRF = open thread) | резерви vs под · ON RRP буфер · SRF usage |
| 3 | Цена на парите | NY Fed `rates/secured/sofr` (no-auth) | SOFR−IORB ≥ 0 устойчиво · опашка p99−p25 |
| 4 | Аукциони (2 оси) | TreasuryDirect `auctions_query` (no-auth) | bid-to-cover z по тенор (red) · PD-дял z тенор-релативен (amber: дилърски бекстоп = другите се отдръпват) |
| 5 | Ливъридж (2 оси) | OFR STFM DVP обем + CFTC TFF `gpe5-46if` нетна къса (no-auth) | спад на repo обема ИЛИ разпад на нетната къса от зареден връх = форсиран basis unwind |

**Context панел (не лампи):** TGA (FRED `WTREGEN`, канонично ТУК) · DGS10 · DGS30.

## Target принципи (Фаза-2 съответствие)

1. **Identity guard** — серия пинната по ID, не по име/LIKE (`config/sources.yaml`); schema assert при fetch.
2. **health.json per source** — status/as_of/error всеки run.
3. **No silent zero** — счупен/нерезолвнат източник = `null` + health badge, никога 0.
4. **Window етикети** — всеки percentile/z носи прозореца си.
5. **schema_version** в lamps/composite/funding_state.
6. **Допускания label-нати с дата** — всички прагове в `config/sources.yaml` (provisional).

## Изходи (`data/`)

- `lamps.json` — 5 лампи + health
- `composite.json` — скор 0–10 + категорична присъда (BG) + context
- `funding_state.json` — handoff (vrm-state модел) за 3 консуматора: VRM pre-KS лампа · macro-satellite · us-macro stability карта
- `health.json` — per-source свежест

## Стартиране

```bash
pip install -r requirements.txt
export FRED_API_KEY=<ключът>          # никога в код/commit
PYTHONPATH=src python -m funding_radar.run
PYTHONPATH=src python tests/test_core.py   # офлайн детерминистичен тест
```

## Статус (S16, 2026-06-22)

✅ **Runnable ядро** — gate 1 (резолюция) + fetchers + 5 лампи + composite + JSON изходи; жив run зелен (всички 5 лампи активни, нула мъртви източници).

✅ **Калибрация (gate 3)** — бектест срещу реални епизоди (септ-2019 · март-2020 · 31.10.2025 SRF $29.4млрд · спокойни контроли). Виж `CALIBRATION.md`.

✅ **Лампа 5 двуосова (v1.1)** — CFTC leveraged-funds позиционна ос добавена към обемната; март-2020 basis unwind вече пали 🔴 (композит 4.0→7.0). Метод: `calibration/lamp5_detail.py`.

✅ **Лампа 3 rolling-устойчивост (v1.1)** — 5-дн среден SOFR−IORB спред.

✅ **Лампа 4 PD-дял ос (v1.1)** — тенор-релативен primary-dealer дял, amber-онли допълнителен път (red остава чисто bid-to-cover); хваща дилърски бекстоп (Q4-2023 auction tail). Метод: `calibration/lamp4_pd_detail.py`.

⏳ **Остава (follow-up):** daily/weekly CI (FRED_API_KEY repo secret; CFTC+TreasuryDirect no-auth) · consumer patch в us-macro-dashboard · GitHub repo + deploy (чака одобрение — gate 4; репото още не е git-нато). **Няма повече v1.1 остатъци по лампите.**
