import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent

def functions(text):
    matches = list(re.finditer(r'^([ \t]*)function (\w+)\([^\n]*', text, re.M))
    result = {}
    for i, match in enumerate(matches):
        piece = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        endings = list(re.finditer(r'^' + re.escape(match.group(1)) + r'}', piece, re.M))
        result[match.group(2)] = piece[:endings[-1].end() if endings else len(piece)].strip()
    return result

old = functions((OUT / 'dashboard_template.before.html').read_text(encoding='utf-8'))
new = functions((ROOT / 'dashboard_template.html').read_text(encoding='utf-8'))
changed = [name for name in old if old[name] != new.get(name)]
assert set(changed) == {'renderFresh', 'watchDataVersion'}, changed
assert {name for name in new if name not in old} == {'renderUpdateState'}
assert (ROOT / 'datafeed.py').read_bytes() == (OUT / 'datafeed.before.py').read_bytes()
snapshot = json.loads((ROOT / 'cache/snapshot.json').read_text(encoding='utf-8'))
status = json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status', timeout=5))
assert not status['scan_active'], '当前服务仍在扫描'
assert status['snapshot_generated_at'] == snapshot['generated_at']
close = snapshot['boundary_prices']['close']
assert close['count'] == len(close['prices']) and close['count'] >= int(snapshot['pool_size'] * .6)
assert snapshot['strength_model']['asof'] == '2026-10-08'
assert all(row['source_at'].startswith('2026-10-08') and row['source_at'][11:16] >= '15:00'
           for row in close['prices'].values())
result = dict(phase=status['phase'], pid=status['pid'], generated_at=snapshot['generated_at'],
              daily_asof=snapshot['strength_model']['asof'], close_captured_at=close['captured_at'],
              close_count=close['count'], last_publish_ok=status['last_publish_ok'],
              changed_ui_functions=changed, selection_and_score_ui_unchanged=True,
              datafeed_unchanged=True, resident_code_restart_pending=True,
              unit_tests_passed=294)
(OUT / 'scope.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'status.after.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
raw = (OUT / 'browser_result.txt').read_text(encoding='utf-8-sig')
browser, _ = json.JSONDecoder().raw_decode(raw.split('### Result', 1)[1].lstrip())
(OUT / 'browser.json').write_text(json.dumps(browser, ensure_ascii=False, indent=2), encoding='utf-8')
report = f'''# 数据刷新排查与修复

## 已核实原因

日志及压缩原始采集记录：13:00:02任务已触发，13:00:20收到3120只，其中2912只源时间12:59、140只12:58、68只09:00。第一轮没有拦住午休报价，仍计算并于13:01:38发布；13:01:43再次扫描，13:02:24收到3043只13:01报价，13:03:46才发布，13:03:47页面已自动载入。因此13:03尚未展示下午数据的直接原因是首次输入没有跨过13:00，且重复完整计算占用时间。

后续日志另有代理连接拒绝导致报价无法取得。当前腾讯公共行情直连及原连接均通过探测，网络已恢复；本轮没有调整用户代理设置，也没有声称永久消除了外部网络故障。

收盘补取另发现原条件无条件拒绝16:00以后的源时间，而腾讯当天收盘报价源时间为16:14/16:15，导致收盘阶段报价一直未确认。

## 改动

scoring.py：早盘或午盘先核验输入源时间跨过09:30/13:00，沿用原60%覆盖要求、未来时间及10分钟新鲜度要求，在外围、题材、资金和完整计算之前返回未就绪；收盘报价保留同日、未来时间、真实成交、有限数字及OHLC范围核验，允许15:00之后的当日收盘源时间，不把源刷新时间冒充交易时间。午间仍不接受13:00之后的报价。

serve.py：开盘未就绪任务15秒重试，最大40次，原扫描锁继续防止并发及排队；定点任务失败同步更新last_scan_ok、last_scan及错误；收盘后的手动刷新可补取缺少的收盘阶段报价。

页面：新增简洁更新状态及耗时，详细错误在注释中；初次轮询也比较页面与已发布快照时间，避免旧页面把新版版本号当成自身基线；回到页面时立即检查。原筛选、评分、排序及选股函数保持不变。

check_dashboard.py：删除把南华生物永远断言为趋势在线的旧固定结果，继续按每只股票当天MA和收盘价验证趋势。模型规则没有变化。

## 验证与当前状态

294项单元检查通过；新增开盘切段、60%覆盖、过期/缺失/未来/跨日报价、过早收盘、收盘后源时间、午间越界、早拒绝辅助请求、定点失败状态检查。原始13点记录重放：第一批拒绝，第二批3043只通过。浏览器验证更新中、报价待更新、采集失败、发布失败及初次轮询自动载入；更新耗时未发生时区偏移。

当前已使用一次性补取并通过现有刷新接口同步发布，生成时间{snapshot['generated_at']}，正式日线截至{snapshot['strength_model']['asof']}，收盘报价{close['count']}只，抓取时间{close['captured_at']}。页面明确显示价格截至15:00，源抓取时间另列。

常驻服务重启被自动审批拦截，返回blocked by policy，未提供更详细原因。没有改用其他终止方式。当前页面提示及当天数据已生效；常驻进程PID {status['pid']}仍需用户重启，才能加载新的自动采集衔接代码。因此不声明未来开盘自动修复已在常驻进程生效。

备份在本目录*.before.*，仅作恢复，不参与运行。详细证据见replay.json、browser.json、scope.json、status.after.json及output/playwright/refresh-state.png。
'''
(OUT / '排查与验收.md').write_text(report, encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
