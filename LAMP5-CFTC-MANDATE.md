# Лампа 5 v1.1 — CFTC leveraged-funds кръст · МАНДАТ за нова сесия

> Cold-readable. Gate-3 калибрацията (2026-06-22) завърши и петте лампи; лампа 3 rolling
> (v1.1) също. **Тази сесия = довърши лампа 5** — добави позиционната ос към обемната.
> Чети първо: `CALIBRATION.md` · `README.md` · spec
> `tsachev-ops/.../design/treasury-funding-radar-spec.md` · памет `project_init22_s16_funding_radar`.

## Защо е живо (проблемът)

Лампа 5 сега вижда само **половината картина**: OFR DVP repo обемен z (63д). Spec-ът иска
двете оси: **„спад на repo обема ПРИ растящи къси позиции = принудително разграждане на basis
trade"**. Самият обемен спад е частичен — в март-2020 и окт-2025 обемът беше ВИСОК (z+2.57/+4.09),
затова лампата мълчеше, докато basis trade-ът се разпадаше. Позиционната ос (CFTC leveraged funds
нетни къси в UST фючърси) е липсващата половина.

## Сигналът (дизайн)

Лампа 5 = две оси, комбинирани:
1. **Обем** (съществуваща): OFR DVP repo обемен z. Спад = разграждане.
2. **Позиция** (НОВА): CFTC **Leveraged Funds** нетна КЪСА позиция в UST фючърси (TFF report).
   Големи/растящи къси = натрупан basis trade → unwind риск.
- **Разграждане (red):** repo обемът пада ПРИ голяма/растяща нетна къса (двете заедно = форсиран unwind).
- Голяма къса сама = натрупан риск (amber/контекст). Обемен спад сам = частичен (текущото).

## Gate 1 — резолюция на източника (ПЪРВО, anti-illusion: не гадай)

**Архитектурно решение (вземи го, не релитигирай):** радарът е **standalone Зона-1** (spec +
increment). НЕ свързвай кросрепо към data-core базата (`cot_<key>_net`) — това чупи standalone
принципа (както ETF-Dashboard multi-function урокът). Вместо това: **директен CFTC fetch**, със
собствен fetcher (консистентно с NY Fed/TreasuryDirect/OFR no-auth source-овете).

- CFTC публикува COT през **data.cftc.gov (Socrata, no-auth)**. Трябва **Traders in Financial
  Futures (TFF)**, категория **Leveraged Funds**, UST фючърси.
- [VERIFY в сесията] точния Socrata dataset ID + полевите имена (lev_money_positions_short_all и т.н.).
  Пробвай и `publicreporting.cftc.gov`. Резолвни като gate-1 преди build (както този радар резолвна
  FRED/NY Fed).
- **Пинвай UST фючърсите по CFTC код, НЕ по име** (WTI splice / LIKE-rename урокът от S13 COT миграцията).
  UST коди за проверка: 10Y note · 5Y · 2Y · Ultra · T-Bond. Точните `cftc_contract_market_code`-ове
  → verify срещу CFTC, пинни ги в `config/sources.yaml`.

## Калибрационни епизоди (basis-trade стрес)

- **Март 2020** — basis trade се взриви; leveraged funds бяха рекордно къси и форсирано разплетоха.
  Лампа 5 трябва да светне (сега е зелена там — точно дупката).
- **2024-2025** — рекордни leveraged-funds къси в UST фючърси (натрупване). Калибрирай прага на
  „голяма къса" срещу този период.
- [VERIFY числата срещу CFTC преди да са котви — anti-illusion.]
- Бектест харнесът `calibration/backtest.py` вече тегли OFR обема; добави CFTC оста за същите as-of дати.

## Интеграционни точки

- `sources.py`: нов `fetch_cftc(...)` (Socrata no-auth, schema assert като другите).
- `lamps.py` `lamp5_leverage`: приеми и CFTC нетна къса; комбинирай двете оси. Запази `cftc_leveraged_cross`
  ключа в detail (вече placeholder=None).
- `config/sources.yaml`: пинни CFTC dataset + UST коди + прагове (с [CALIBRATED дата+метод] етикет).
- `tests/test_core.py`: офлайн тестове за комбинираната логика (две оси).
- `docs/index.html`: лампа 5 detailLine да покаже и позицията.

## Anti-illusion

- CFTC коди пиннати, не по име. Числата на епизодите verify срещу CFTC. [CALIBRATED] етикети с дата+метод.
- Cardinal: моделът не пише в data-core; радарът е standalone, собствен fetch.

## Среда

- Бектест харнес + калибрационни скриптове съществуват в `calibration/`.
- Тестове: `python tests/test_core.py` (сега 14 офлайн).
- Run: `FRED_API_KEY=<ключ> PYTHONPATH=src python -m funding_radar.run` (FRED ключ env-only за FRED
  частите; CFTC е no-auth). Preview: `funding-radar` порт 8139.
- Репото още НЕ е git-нато; deploy = gate 4 (отделно одобрение). Тази сесия е код, не deploy.

## Остатъци след лампа 5

- v1.1: лампа 4 PD-дял тенор-релативен (лек, без нов източник).
- CI (daily+weekly) · consumer patch в us-macro-dashboard · GitHub repo + deploy = gate 4.
