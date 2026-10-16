import json,hashlib,csv,io,difflib
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
import ui_payload
O=Path(__file__).parent;root=Path.cwd()
v=json.loads((O/'live_verification.json').read_text('utf8'));f=json.loads((O/'frozen_verification.json').read_text('utf8'));a=json.loads((O/'post_publish_status.json').read_text('utf8'));b=json.loads((O/'pre_refresh_status.json').read_text('utf-8-sig'))
assert a['data_version']!=b['data_version'] and a['ui_generation']!=b['ui_generation'] and a['refresh']['ok']
log=(O/'browser_check.txt').read_text('utf8')
result,_=json.JSONDecoder().raw_decode(log.split('### Result',1)[1].lstrip())
assert result['generation']==v['ui_generation']
by={r['id']:r for r in json.loads((root/'cache/snapshot.json').read_text('utf8'))['board_catalog']}
evidence={}
for kind in ('industry','theme'):
    raw=(O/(kind+'-before.csv')).read_bytes()
    assert raw==(O/(kind+'-many.csv')).read_bytes()==(O/(kind+'.csv')).read_bytes()
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    for r in rows:assert json.loads(r['完整模型依据'])==by[r['ID']]['market_strength'] and r['UI版本']==v['ui_generation']
    evidence[kind]=dict(rows=len(rows),browser_downloads_byte_equal=True,http_byte_equal=True,all_full_models_equal=True,sha256=hashlib.sha256(raw).hexdigest())
assert (O/'stocks-browser.csv').read_bytes()==(O/'stocks.csv').read_bytes()
evidence['stocks']=dict(rows=v['stock_export_rows'],browser_http_byte_equal=True)
evidence['members']=result['members']
fo=O/'frozen-browser';fr,_=json.JSONDecoder().raw_decode((fo/'browser_check.txt').read_text('utf8').split('### Result',1)[1].lstrip());fv=json.loads((O/'frozen_ui_verification.json').read_text('utf8'))
assert fr['generation']==fv['generation']
fb={r['id']:r for r in ui_payload.full(fr['generation'])['board_catalog']}
fixture_evidence={}
for kind in ('industry','theme'):
    raw=(fo/(kind+'-before.csv')).read_bytes()
    assert raw==(fo/(kind+'-one.csv')).read_bytes()==(fo/(kind+'-many.csv')).read_bytes()==(fo/(kind+'.csv')).read_bytes()
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    assert len(rows)==(13 if kind=='industry' else 3)
    for r in rows:assert json.loads(r['完整模型依据'])==fb[r['ID']]['market_strength'] and r['UI版本']==fv['generation']
    fixture_evidence[kind]=dict(rows=len(rows),three_browser_downloads_byte_equal=True,http_byte_equal=True,full_models_equal=True)
assert (fo/'stocks-browser.csv').read_bytes()==(fo/'stocks.csv').read_bytes()
assert len(list(csv.DictReader(io.StringIO((fo/'stocks.csv').read_text('utf-8-sig')))))==511
fixture_evidence['stocks']=dict(rows=511,browser_http_byte_equal=True)
fixture_evidence['members']=fr['members']
evidence['labelled_frozen_fixture']=fixture_evidence
(O/'browser_verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8')
changes=[];(O/'diffs').mkdir(exist_ok=True)
for name in ('market_strength.py','ui_payload.py','serve.py','radar_ui.js','test_market_strength_rework.py'):
    source=root/name;old=O/'baseline'/name
    changes.append(dict(file=name,sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    diff=''.join(difflib.unified_diff(old.read_text('utf-8-sig').splitlines(True) if old.exists() else [],source.read_text('utf8').splitlines(True),fromfile='before/'+name,tofile='after/'+name))
    (O/'diffs'/(name+'.diff')).write_text(diff,'utf8')
(O/'changed_files.json').write_text(json.dumps(changes,indent=2),'utf8')
lines=[
'# 三项返工验收交付',
'',
'本次仅修负责人独立验收指出的三处问题。评分版本仍为 `'+v['version']+'`；config.py 与返工前备份逐字节相同，评分权重、尺度、65/80/45边界、ATR档位、成员覆盖和采集周期均未改动，没有新增等待确认。',
'',
'## 修复结果',
'',
'1. 报价先检查评价日、未来时间和源会话合法性，随后才考虑年龄豁免。正式收盘核验须含明确的评价日和收盘后时间，收盘报价只接受当日15:00至15:02供应商延迟更新窗口；年龄豁免不再放行昨日、未来、上午或休市报价。午休只延续上午收市边缘有效行情与既有11:31/11:32延迟更新时间，保留原来源时间。非法报价的相关评分为null，记录原因。',
'2. 行业、题材CSV通过 /__ui/export 的board请求按指定UI generation读取不可变detail表中的完整后端对象，保持当前筛选及后端排序。页面摘要或此前点过哪些详情不影响导出。原股票导出契约继续保留。',
'3. 两类板块详情恢复“在个股页查看该板块全部成员”。进入成员页清空搜索、阶段和分页，将MS_VIEW.stocks.scope设置为all；趋势强/情绪强和排序仅在确认成员交集内运作。清除成员筛选恢复全池all范围，同版成员详情正常。',
'',
'## 测试与冻结输入',
'',
'新增 test_market_strength_rework.py 共8项测试，含独立验收全部时间负例与有效对照、完整板块导出不随详情读取变化、成员入口/子集排序/清除及按钮恢复。原模型及集成42项加新增8项：50项通过（focused_tests.txt）。最终完整回归537项通过（regression.txt）。一次重启扫描期间的全量测试因全局写锁出现7项PipelineBusy，保留regression_during_scan.txt；服务空闲后完整重跑全部通过。',
'',
'原冻结输入没有覆盖；再次逐项复算3120只股票、539个板块，完整模型对象与原comparison.json一致，原始输入、成员顺序和指数字段未变（frozen_verification.json）。四种独立验收非法报价均两轴null、focus=0；真实收盘、11:31及正常午后对照E86、focus=10（time_boundaries.json），这是合成流水线证据，不是实盘收益。',
'',
'## 实际发布与浏览器证据',
'',
'最终PID '+str(v['pid'])+'；运行/快照/本地实现哈希一致：`'+v['implementation_hash']+'`。正常POST /__refresh收到started/quick，最终ready、last_scan_ok/last_publish_ok/refresh.ok均为true。data_version由 '+str(b['data_version'])+' 更新为 '+str(v['data_version'])+'；UI generation由 '+b['ui_generation']+' 更新为 `'+v['ui_generation']+'`。收据与状态见refresh_receipt.json、pre_refresh_status.json、post_publish_status.json。',
'',
'本次报价采集时间 '+v['source_at']+'。当前强势 '+str(v['counts']['focus'])+' 只，强势板块 '+str(v['board_counts']['focus'])+' 个；实际股票导出 '+str(v['stock_export_rows'])+' 行，行业 '+str(v['export_counts']['industry'])+' 行，题材 '+str(v['export_counts']['theme'])+' 行。',
'',
'实盘刷新返回的源时间含12:05等午休非法时段，恢复保护后相关两轴均不可用，当前强势为0；没有为了保持511只而放宽校验或回写旧行情。实盘摘要、详情、CSV与运行版本仍一致。下列非空下载验收单独使用原11:31冻结输入，明确标记“冻结输入验收，非当前实盘发布”，未激活或替换生产看板。',
'',
'在上述标记清楚的冻结输入HTTP页面，真实浏览器分别在未打开详情、打开1个详情、打开3个详情后点击行业与题材导出：行业13行、题材3行，各自三份文件逐字节一致，也与同版实际HTTP导出逐字节一致；每行完整模型与该UI版本不可变完整对象相等（browser_verification.json内labelled_frozen_fixture；frozen-browser/industry-before/one/many.csv、theme-before/one/many.csv）。股票511行浏览器下载与实际HTTP完整导出逐字节一致（frozen-browser/stocks-browser.csv、stocks.csv）。这份冻结验证不声称是最新实盘名单。',
'',
]
for m in fr['members']:
    lines.append('实际点击 '+m['name']+' → 查看全部成员 → 趋势强/趋势排序 → 情绪强/情绪排序 → 成员详情 → 清除成员筛选：全部成员 '+str(m['count'])+'，趋势强 '+str(len(m['subsets']['trend']))+'，情绪强 '+str(len(m['subsets']['emotion']))+'；清除后恢复全池 '+str(m['clear_count'])+'。名单及顺序逐项与后端确认成员交集一致，详情UI版本相同。')
lines+=['','页面与服务检查均通过（dashboard_check.txt、live_service_check.txt）。实际截图：','',
'![题材成员详情（冻结输入）](frozen-browser/theme-member-detail.png)','',
'![行业成员详情（冻结输入）](frozen-browser/industry-member-detail.png)','',
'![最终雷达](radar.png)','',
'返工前源文件、配置、快照、页面及PID/版本独立备份在本目录baseline，哈希清单backup_manifest.json。修改范围见changed_files.json与diffs；未覆盖原轮备份、冻结输入、负责人独立报告或原验收证据。']
(O/'三项返工验收报告.md').write_text('\n'.join(lines)+'\n','utf8')
print('Report and browser CSV/model/member evidence verified.')
