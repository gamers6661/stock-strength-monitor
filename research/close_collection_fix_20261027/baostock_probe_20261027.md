# Baostock login / daily-history probe (read-only)

- Local time reported by the process: 2026-10-27 15:50:54.
- Imported the existing vendored package from `D:\股票强势监测\cache\stock_selection_v3\vendor\baostock`; no installation was attempted.
- Set Python socket default timeout to 10 seconds before the probe.
- `bs.login()` returned `error_code=10002007`, `error_msg=网络接收错误。`; console also emitted `timed out` / `接收数据异常，请稍后再试。`.
- Because login did not succeed, `query_daily_history_k_AStock('2026-10-27')` was not called. No dates, row counts, `adjustflag`, or 002191/000001 rows are available from this probe; this is a login/network failure, not evidence that 2026-10-27 has no data.
- Attempted logout in `finally`; it also printed a timeout. Restored the prior socket default timeout. Did not call `refresh_bulk`, access the amount database, change service state, edit source, or install dependencies.
