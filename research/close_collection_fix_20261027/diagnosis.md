# 2026-10-27 正式收盘日线采集只读诊断

## 结论

- 确认 15:05 起该收盘扫描的 2,952 个日线增量请求全部失败，收盘复盘门槛因此得到 0/3,030 覆盖。`logs/serve.log:139345-139395`：15:05:04 close 阶段开始；实时行情后续记录 3,030/3,122（`139378`）；日线批次 `requested=2952, failed=2952`（`139394`）；`139395` 明确因 0/3030 而保留上一份榜单。
- 15:37:08 的初始单股样本仅证明 `days=5` 参数路径当时可用；它本身不能排除生产 `increment_days` 参数、批处理并发或共享 host 冷却。后续补充的生产参数验证见“追加验证”。
- 同时确认成功的单股请求发生在失败批次之后，不能证明 15:05 的源端状态；也不能由两只样本推断当时全池可得。当前 `cache/market.db` 仍 max(date)=2026-10-26；检查前无业务库写入。
- 根因的精确异常类别未保留。`datafeed.py:820-825` 将 fetch_kline 中任何异常统一转换为 `request_error`，没有日志/异常类型；SQLite 状态截至 15:24:58 对多只股票只记录 `kind=request_error`。所以“15:05 源延迟”是可能解释但未证实；请求链路/传输异常也同样符合证据。日志里的“腾讯行情批次 timed out”发生在全池实时报价链路，不足以证明日线端同样超时。

## 真实源端样本

| 本地采样时间 | 代码 | API函数结果 | 最新记录 | basis |
|---|---|---|---|---|
| 2026-10-27 15:37:08 | 600519 | 成功，6行，约0.33秒 | 2026-10-27 O=1343.88 H=1357.00 L=1338.01 C=1355.90 V=3,866,900 | qfq / tencent_qfqday |
| 2026-10-27 15:37:08 | 000001 | 成功，6行，约0.25秒 | 2026-10-27 O=11.27 H=11.55 L=11.24 C=11.47 V=152,929,200 | qfq / tencent_qfqday |

参数来自当前配置：hosts 顺序为 `web.ifzq.gtimg.cn/appstock/app/fqkline/get`、`proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get`、`proxy.finance.qq.com/appstock/app/fqkline/get`；代码拼接为 `{host}?param={sh|sz}{code},day,,,{days},qfq`（`datafeed.py:754-780`）。样本的首选源请求及 parser 都可用，故当前参数与返回解析不是普遍性故障的支持性证据；历史失败时段的具体返回未留档。

## 重试/缓存

最新数据库失败状态示例：603506、601016、603225 均为 `checked=2026-10-27 15:24:53`、`data_fetch.checked_at=15:24:58`、`failures=6`、`next_retry=15:40:53`、`kind=request_error`。失败时按指数退避设置 next_retry（`history_increment.py:221-233`）；因此 15:24 后重复扫描中的 `requested=0`（如 `logs/serve.log:139913` 及以后）是状态退避抑制请求，不是缓存返回了旧 K 线伪装成功。15:05-15:24 间多轮 `requested=2952` 仍全部失败，故退避不是首次 0 覆盖的起因，而是失败后的重试间隔。

`cache/market.db` 在只读 URI 下查询，max K 线日期为 2026-10-26。`kline_fetch_state` 本身是此次失败状态记录；没有修改业务库、缓存或服务。

## 最小修复建议

1. 在 `datafeed.fetch_klines_bulk.work()` 捕获异常时保留受限诊断字段：异常类型/短消息、所用 host、尝试数、请求耗时；在批次结果和状态中按 timeout / HTTP / JSON / schema / valid-empty 分类，并对批次汇总各类计数。不得记录请求头、敏感凭据或整段响应体。
2. 对“有效空响应”与“请求异常”分开记录。当前 `fetch_kline()` 只有请求异常才尝试下一个 host（`790-793`）；一个 host 连续返回空两次便返回空，不继续故障转移（`771-789`）。若证据显示当时首选 host 提前发布滞后，应调整空响应时的跨 host 试探/对等源验证，并仍要求覆盖率门槛通过后发布。
3. 保持收盘正式日线的现有覆盖校验。`history_increment.py:166-170` 会要求有效行且不落后于目标日；不建议通过旧报价合成日线或降低收盘覆盖门槛。

## 本次操作范围

只读了源码、日志、配置和 SQLite（URI mode=ro），对两只股票发起独立只读行情请求。未修改项目源文件、业务数据库、缓存，未启动全池任务或重启服务。证据文件由本诊断新建。


## 追加验证：生产增量参数与 host 冷却放大

### 生产增量参数真实请求

2026-10-27 15:39:25，以 `days=config.KLINE['increment_days']=20`、`workers=config.KLINE['workers']=10` 调用原始 `fetch_klines_bulk`，5 只 `600519, 000001, 300750, 601318, 000333` 共返回105条（每只21条），每只最新日均为2026-10-27；5只均 `fetch_states.kind=ok`，互为同批成功 peer，整批耗时0.484秒，`truncated=False`。这排除当前生产增量参数或批处理并发存在必现的普遍参数/解析错误；不能回推15:05当时情况。

### 共享冷却受控模拟

在独立、未改源码的 Python 进程中对 `datafeed.http_get` 做运行时mock，无网络访问、无文件/业务库写入：先把两个备用 host 设为处于60秒冷却，仅保留首选 host可用；对一个引发请求的 `fetch_kline('600519', days=20)`，mock首选host一次网络超时。源码 `fetch_kline:790-793` 将首选host写入共享 `_KLINE_HOST_COOLDOWN` 后抛出；此刻三个 host 全部在冷却。

紧接着以 SQLite 只读读取的2,952个实际股票代码调用原始 `fetch_klines_bulk`，`workers=10`。它在0.062秒内结束：2,952个都进入 `fetch_states`、全部 `kind=request_error`、0条K线返回、`truncated=False`，且无额外 HTTP 调用。对应控制路径是 `datafeed.py:766-770`（先排除冷却host，若没有可用host立即抛异常）、`790-793`（请求异常即对该host冷却60秒）、`820-825`（bulk把异常统一折叠为request_error）、`840-847`（仅 FuturesTimeoutError 才设置 truncated）。这确认共享冷却具备将“剩余可用host的一次错误”快速放大到全批失败且不标记超时的机制。

该模拟的前置条件是两个备用host已经在冷却；production服务当时的内存 `_KLINE_HOST_COOLDOWN` 未从日志持久化，不能确认真实15:05是否正好处于该状态。因此：**放大机制已通过源码与mock确认，且与当日2,952/2,952 request_error、truncated=False吻合；是否为当日直接触发链仍属强推断而非现场状态证据。**真实生产请求五股全成功也说明源端后来恢复/可用，但无法反推失败窗口。

### 对主线程候选最小修复的判断

受控复现支持以下最小修复方向：将“所有host冷却、没有发起网络请求”识别为独立的 `KlineHostCooling`/`source_cooldown`，bulk保留它和实际HTTP/超时/解析失败的差异；history_increment 对 source_cooldown 不累增个股真实失败次数、不写长退避并统计deferred；保留真实单股请求失败的指数退避和正式收盘覆盖门槛。它能避免2,952个未发请求的代码被误计成各自真实取数失败。此次只读诊断未修改源代码，也未运行测试。
