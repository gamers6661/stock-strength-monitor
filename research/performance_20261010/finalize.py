import difflib
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
import ui_payload
out = Path(__file__).resolve().parent


def browser_result(name):
    text = (out / name).read_text(encoding='utf-8-sig')
    result = re.search(r'### Result\s*\n([^\n]+)', text)
    if not result:
        raise AssertionError(name + ' has no successful result')
    return json.loads(result[1])


browser = browser_result('browser_result_final.txt')
refresh = browser_result('refresh_result_final.txt')
offline = browser_result('offline_result.txt')
assert not browser['mismatches'] and not browser['errors'] and browser['csvEqual']
assert all(refresh['checks'].values()) and refresh['checksExpired'] and refresh['foreignRejected']
assert all(offline['stock'].values()) and offline['board'] and not offline['lazy'] and not offline['networkRequests']
assert offline['hash'] == browser['newCSV']['hash']
assert 'Ran 385 tests' in (out / 'all_tests_final.txt').read_text(encoding='utf-8')
assert '\nOK\n' in (out / 'all_tests_final.txt').read_text(encoding='utf-8')
for name in ('page_check_final.txt', 'live_check_final.txt'):
    assert (out / name).read_text(encoding='utf-8').startswith('OK')
baseline = json.loads((out / 'baseline.json').read_text(encoding='utf-8'))
original_snapshot = gzip.decompress((out / 'snapshot.json.before.gz').read_bytes())
snapshot = (root / 'cache/snapshot.json').read_bytes()
assert hashlib.sha256(original_snapshot).digest() == hashlib.sha256(snapshot).digest(), 'Market input changed'
token = ui_payload.active_generation()
page_bytes = (root / 'dashboard.html').stat().st_size
wire_bytes = len(ui_payload.blob(token, 'page.gz'))
assert page_bytes < 10_000_000
metrics = dict(baseline=baseline, page_bytes=page_bytes, wire_bytes=wire_bytes,
               ui_generation=token, snapshot_sha256=hashlib.sha256(snapshot).hexdigest(),
               browser=browser, refresh=refresh, offline=offline,
               cache_bytes=sum(p.stat().st_size for p in ui_payload.store_root().glob('*.db')))
(out / 'results.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
changes = []
for name in ('make_dashboard.py', 'serve.py', 'dashboard_template.html', 'check_dashboard.py', 'check_live_service.py'):
    changes.extend(difflib.unified_diff((out / (name + '.before')).read_text(encoding='utf-8').splitlines(True),
                                      (root / name).read_text(encoding='utf-8').splitlines(True),
                                      fromfile=name + '.before', tofile=name))
for name in ('ui_payload.py', 'ui_client.js', 'csv_export.js', 'csv_runner.js', 'stock_list_fields.json', 'test_ui_payload.py'):
    changes.extend(difflib.unified_diff([], (root / name).read_text(encoding='utf-8').splitlines(True),
                                      fromfile='/dev/null', tofile=name))
(out / 'changes.diff').write_text(''.join(changes), encoding='utf-8')
report = f'''# 第一轮性能优化与原计划核查

## 范围和结果

本轮完成页面与数据加载优化。评分公式、筛选条件、ATR与量价结构判断、数据源覆盖、常规五分钟刷新、竞价/午间/收盘边界、七天成员更新均沿用原规则。后端日线计算缓存、历史行情增量采集和各扫描阶段耗时细分留在第二轮，尚未实施；本轮未声称扫描计算变快。

冻结输入为 {baseline['generated_at']} 的行情快照，完成日为2026-10-09。原始 snapshot.json 在实施前后的SHA256一致，未为测试改动股票价格或判断。

| 原计划 | 实施结果 | 核查证据 |
|---|---|---|
| 首屏数据不超过10MB | 页面 {page_bytes/1_000_000:.2f}MB，原页面 {baseline['page_bytes']/1_000_000:.2f}MB；HTTP压缩传输 {wire_bytes/1_000_000:.2f}MB | 文件尺寸、实际HTTP返回及results.json |
| 保留完整股票池与筛选 | 3024只评分样本与96只覆盖样本全部保留 | 599组旧/新浏览器对照全部一致 |
| 详情按需读取 | 走势图、题材关系、完整判断依据、日内路径从同版本地SQLite读取 | 600241实际抽屉验证；点击不请求外部行情 |
| 板块不重复携带完整成员 | 首屏保留成员代码和必要报价；完整成员详情按需读取 | 电池板块29只有效主板成员均有完整姓名及详情 |
| CSV保留完整列、完整筛选结果和顺序 | 原格式代码共享，后台按选中代码顺序读取数据；格式化代码随版本冻结 | 全池3120行、228列，旧版/新版/离线版CSV SHA256完全一致 |
| 列表、详情、导出同一版本 | URL和导出请求必须指定不可变版本；缓存仅保留当前与上一代 | 两代数据实际切换，缓存均带版本；不存在版本返回409，不向新版本偷换 |
| 刷新不重载整个页面 | 更新列表与当前详情，保留查询、筛选、排序、显示数量、页签、手动模式、页面和详情滚动及展开状态 | refresh_result_final.txt的13个检查全部通过；详情真实滚动400像素保留 |
| 中文输入法不受更新干扰 | 组词期间延后数据替换，组词结束后保留焦点 | composition事件实际验证，原搜索输入元素和焦点保留 |
| 完整离线使用能力 | 个股页「完整离线看板」导出同一版本的完整独立HTML | 点击下载后file://打开；图表/路径/成员/CSV完整，无网络请求 |
| 正式后台生效 | 通过项目「停止服务.bat」「打开看板.bat /silent」自动重载，无需用户手动重启 | status_final.json、check_live_service.py通过 |

## 实测

最终浏览器一组对照：旧首页 {browser['oldLoadMillis']/1000:.2f}秒，新首页 {browser['newLoadMillis']/1000:.2f}秒；此前另一组为6.17秒与0.54秒。缓存、机器状态和首次加载会影响数值，这些是本机测量，不是固定速度承诺。最终个股详情 {browser['detailMillis']}毫秒，全池CSV {browser['csvMillis']/1000:.2f}秒。详情二次打开复用同版本缓存。

完整CSV SHA256：`{browser['newCSV']['hash']}`。

385项单元测试、24项浏览器冒烟检查、599组冻结输入对照、正式页面数据契约及正式服务检查均通过。一次最终测试恰好与后台初始化同时运行，因共享写锁出现PipelineBusy；待后台ready后复测385项通过，保留写锁保护。测试日志中的 `[FAIL] 看板生成失败：OSError: publish failed` 是发布失败边界的预期测试输出。

## 使用和维护边界

日常通过「打开看板.bat」使用轻量页面。直接双击日常dashboard.html可查看已内联列表，详情需本地服务；完整离线版包含全部数据，可直接双击使用。CSV后台格式化需要Node.js，本机已安装并实测成功。完整离线HTML约100MB，保存和打开仍比轻量页面耗时，这是用户主动导出完整内容时承担的成本。

两代本地UI缓存当前合计约 {metrics['cache_bytes']/1_000_000:.0f}MB，以索引查询避免每次点击重新解析100MB快照；只保留当前及上一代，独立于行情历史库和判断状态。当前数据版本为 `{token}`。列表字段由stock_list_fields.json声明，未来增加字段时需同步维护并重新核查完整筛选对照。

当前日期为非交易日，正式页面显示最近完成交易日2026-10-09；实时交易时段的未来更新速度不能在休市期间测出。本轮验证了真实本地两代数据切换，未伪造当日行情。

备份：5个修改前源码文件、原始看板和原始快照gzip保存在本目录。临时解压页面验证后删除，离线导出样本压缩保留；研究备份不参与正式判断。

## 证据文件

- results.json：尺寸、加载、CSV哈希、刷新与离线验收。
- browser_result_final.txt：599组旧版/新版冻结对照、图表和板块成员。
- refresh_result_final.txt：两代本地数据切换、状态保持、中文输入法及版本过期。
- offline_result.txt：实际下载入口、完整离线查看与CSV哈希。
- all_tests_final.txt / smoke_final.txt / page_check_final.txt / live_check_final.txt：测试与正式服务结果。
- changes.diff：修改前后差异及新模块。
'''
(out / '计划核查与验收.md').write_text(report, encoding='utf-8')
for name in ('baseline.html', 'offline.html'):
    path = (out / name).resolve()
    assert path.parent == out.resolve()
    if path.exists():
        if name == 'offline.html':
            with path.open('rb') as source, gzip.open(out / 'offline.html.gz', 'wb', compresslevel=1) as dest:
                shutil.copyfileobj(source, dest)
        path.unlink()
print(json.dumps({'page_MB':page_bytes/1_000_000,'wire_MB':wire_bytes/1_000_000,
                  'snapshot_unchanged':True,'report':str(out / '计划核查与验收.md')},ensure_ascii=False))
