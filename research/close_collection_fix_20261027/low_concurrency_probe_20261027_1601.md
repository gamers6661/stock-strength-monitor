# Production K-line bulk probe at workers=2 (read-only)

Probe ran 2026-10-27 16:01:40–16:01:45 in a separate Python process using `D:\_tools\stock-monitor\python\python.exe -X utf8 -B`. It called only `datafeed.fetch_klines_bulk` with `days=config.KLINE['increment_days']=20`, `workers=2`, and `deadline_seconds=45`. No `refresh_bulk`, no save call, no business DB write.

## Selection evidence

Immediately before the request, a SQLite `mode=ro` query confirmed all selected symbols' max K-line date was 2026-10-26. Selection used `cache/snapshot.json` `boundary_prices.close` (close capture 2026-10-27 15:00:24) and `stocks` rows with `traded=1` and `amount_wan>0`; snapshot generated at 15:00:59.

| Code | Name | snapshot amount_wan | snapshot price | max K date before probe |
|---|---|---:|---:|---|
| 603278 | 大业股份 | 185025.0 | 17.40 | 2026-10-26 |
| 002724 | 海洋王 | 209011.0 | 13.09 | 2026-10-26 |
| 600838 | 上海九百 | 39426.0 | 13.31 | 2026-10-26 |
| 003021 | 兆威机电 | 171737.0 | 92.50 | 2026-10-26 |
| 603089 | 正裕工业 | 56188.0 | 11.77 | 2026-10-26 |
| 002535 | 林州重机 | 59115.0 | 3.00 | 2026-10-26 |
| 002696 | 百洋股份 | 143274.0 | 10.70 | 2026-10-26 |
| 603028 | 赛福天 | 30197.0 | 10.33 | 2026-10-26 |
| 603528 | 多伦科技 | 80998.0 | 9.85 | 2026-10-26 |
| 603286 | 日盈电子 | 52580.0 | 53.01 | 2026-10-26 |
| 603280 | 南方路机 | 7425.0 | 29.74 | 2026-10-26 |
| 603171 | 税友股份 | 47271.0 | 46.51 | 2026-10-26 |
| 603081 | 大丰实业 | 35452.0 | 10.28 | 2026-10-26 |
| 600267 | 海正药业 | 74589.0 | 13.60 | 2026-10-26 |
| 603341 | 龙旗科技 | 91013.0 | 39.87 | 2026-10-26 |
| 600785 | 新华百货 | 82274.0 | 13.90 | 2026-10-26 |
| 603636 | 南威软件 | 52099.0 | 8.19 | 2026-10-26 |
| 603337 | 杰克科技 | 204439.0 | 44.39 | 2026-10-26 |
| 603677 | 奇精机械 | 10263.0 | 15.02 | 2026-10-26 |
| 600558 | 大西洋 | 54636.0 | 5.72 | 2026-10-26 |

## Result

- elapsed 5.297s; requested 20; `fetch_state_count=20`; returned 20; `truncated=false`.
- `kind` counts: `ok=20`; `request_error=0`; `source_cooldown=0`.
- All 20 returned 21 bars each, with last date `2026-10-27`.
- No host failover line was emitted. The bulk result does not carry a per-code host field, so the exact responding host is not independently confirmed by this run.

This one 20-symbol sample supports that workers=2 succeeds against the currently configured endpoint state at 16:01. It does not establish sustained or full-universe stability.
