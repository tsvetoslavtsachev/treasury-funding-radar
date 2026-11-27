# Treasury Funding Radar

Зона-1 сетиво (INIT-22 S16). **Funding стрес = същодневна детекция** на принудителния
избор на Фед — долар vs облигации. Лампите не предсказват посоката на активите, а
**близостта и цената на policy отговора**. Същодневна (coincident) стрес-детекция,
отделна от ценовия VRM Kill Switch; **БЕЗ промяна на KS правилата**.

## 5-те лампи

| # | Лампа | Източник (resolved 2026-06-22) | Сигнал |
|---|---|---|---|
| 1 | Банково репо (Adler) | FRED `H8B3092NCBA` (H.8, W) | пробив на структурата от 13-седмични дъна |
| 2 | Fed plumbing | FRED `WRESBAL` + `RRPONTSYD` (SRF през FRED `RPONTSYD`) | резерви vs под · ON RRP буфер · SRF usage |
| 3 | Цена на парите | NY Fed `rates/secured/sofr` (no-auth) | SOFR−IORB ≥ 0 устойчиво · вътрешнодневна дисперсия p99−p25 (cross-sectional разсейване на repo сделките ЗА деня, не времева опашка) |
| 4 | Аукциони (2 оси) | TreasuryDirect `TA_WS/securities/search`, Note/Bond/TIPS/FRN (no-auth; до 27.11.2026 Fiscal Data `auctions_query`) | bid-to-cover z по тенор (red) · PD-дял z тенор-релативен (amber: дилърски бекстоп = другите се отдръпват) |
| 5 | Ливъридж (2 оси) | OFR STFM DVP обем + CFTC TFF `gpe5-46if` нетна къса (no-auth) | спад на repo обема ИЛИ разпад на нетната къса от зареден връх = форсиран basis unwind |

**Context панел (не лампи):** TGA (FRED `WTREGEN`, канонично ТУК) · DGS10 · DGS30.

## Target принципи (Фаза-2 съответствие)

1. **Identity guard** — серия пинната по ID, не по име/LIKE (`config/sources.yaml`); schema assert при fetch.
2. **health.json per source** — status/as_of/error всеки run.
3. **No silent zero** — счупен/нерезолвнат източник = `null` + health badge, никога 0.
4. **Window етикети** — всеки percentile/z носи прозореца си.
5. **schema_version** в lamps/composite/funding_state.
6. **Допускания label-нати с дата** — всички прагове в `config/sources.yaml` (калибрирани `[CALIBRATED 2026-06-22]`).

## Изходи (`data/`)

- `lamps.json` — 5 лампи + health
- `composite.json` — скор 0–10 + категорична присъда (BG) + context
- `funding_state.json` — handoff (vrm-state модел) за 3 консуматора: VRM pre-KS лампа · macro-satellite · us-macro stability карта
- `health.json` — per-source свежест
- `lamps_history.csv` — историята на лампите по дни (ПРОЛЕТР2, 25.11.2026): ред на лампа на ден, `жив` от пуска или `дописан` от `backfill.py`; чете я блокът „Парите“ (`data-core\migrations\m_pari`)

## Историята, аукционите и процедурата (ПРОЛЕТР2, 25.11.2026)

- Живият пуск (CI, делнично) сам допълва `lamps_history.csv`; ръчна работа няма. Проверката е в съботния ритуал, стъпка А13: ред `жив` за петъка за петте лампи.
- Лампа 4 носи една дата навсякъде: последният купонен аукцион с резултат (`as_of_kind`); над 45 дни без такъв е сива с причина.
- Аукционите се теглят целите, страница по страница; ако събраното не е `meta.total-count`, е грешка на източника, не тихо рязане. До 25.11.2026 беше една страница от 300 реда (около 9 месеца вместо 400 дни): живите редове до тогава носят рязането, дописаните не.
- `backfill.py` се пуска наново само когато се смени сметката на лампа; тогава дописва всички `дописан` редове със същите функции, а живите не пипа. Сверката с git: `python -m funding_radar.backfill --verify-git`.

## Лампа 4 от TreasuryDirect (ПРОЛЕТБ2, 27.11.2026)

- Fiscal Data `auctions_query` няма резултати след 15.10.2026 (последният купонен е от 08.10), затова лампа 4 беше сива. От 27.11.2026 тя тегли от TreasuryDirect `TA_WS/securities/search`, типовете Note, Bond, TIPS и FRN; правилото не е пипано.
- Четецът дава същите полета и същите числа като Fiscal Data: универсумът е securityType Note/Bond (с TIPS и FRN, както беше), PD-делът е `primaryDealersCompetitiveParAwarded / grandTotalParAwarded` (= `primary_dealer_accepted / total_accepted`). Техническите оферти по 25 млн. отпадат.
- **Цветът е само от номиналните купони** (решение на Ц., 27.11.2026). TIPS и FRN се смятат в свои групи и стоят в `detail.context_tenors` само за сведение. Смесени с номиналните те сменяха цвета в 70 от 913 седмици (червеното от 25.09.2026 беше 10-годишен TIPS) и заглушаваха лято 2013, декември 2018 и ноември 2023; в свои групи с глас утрояваха фалшивите червени заради късата си история. Методът и числата: `python calibration/lamp4_split_scan.py`. Историята на лампа 4 е дописана наново (523 реда, 74 с нов цвят; другите лампи и живите редове не са пипани).
- Сверката: `python calibration/lamp4_td_parity.py` (05.2008 до 08.10.2026: 1749 общи аукциона без разминаване, 906 седмични среза на лампата с еднакъв изход; петте реда само във Fiscal Data са технически).

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

✅ **Deploy (gate 4) — живо от 2026-06-22..24:** публично repo + GitHub Pages светофар + делничен CI (FRED_API_KEY repo secret; CFTC+TreasuryDirect no-auth) + consumer adapter в us-macro-dashboard. **Няма повече v1.1 остатъци по лампите.**
