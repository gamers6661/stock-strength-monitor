import csv,difflib,gzip,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config,radar_opportunity as ro
OUT=Path(__file__).resolve().parent
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def browser(name):
    text=(OUT/name).read_text(encoding='utf-8-sig');assert '### Error' not in text,text[-1000:]
    return json.JSONDecoder().raw_decode(text.split('### Result',1)[1].lstrip())[0]
receipt=read('published_refresh.json');live=browser('browser_live.txt');stages=browser('browser_stages.txt')
with gzip.open(OUT/'published_refresh_snapshot.json.gz','rt',encoding='utf-8') as f:snap=json.load(f)
model=snap['radar_opportunity'];archive=model['last_close_review']
assert live['generation']==receipt['after']['ui_generation']==live['end_generation']
assert live['close']==archive
assert model['repair_version']==ro.REPAIR_VERSION
assert model['implementation_hash']==receipt['after']['snapshot_radar_opportunity_hash']==ro.IMPLEMENTATION_HASH
rows={r['code']:r for r in snap['stocks']+snap['coverage_catalog']}
assert live['detail']['item']['radar_opportunity']==rows[live['detail']['item']['code']]['radar_opportunity']
proof=dict(data_version=receipt['after']['data_version'],generation=live['generation'],no_page_errors=not live['errors'],archive_equals_disk=True,detail_opportunity_equals_disk=True,csv={})
for name,kinds in [('close.csv',None),('close-sustained.csv','持续进攻')]:
    expected=[r for r in archive['stock_rows'] if not kinds or kinds in r['labels']]
    with (ROOT/'output/playwright/radar-repair'/name).open(encoding='utf-8-sig',newline='') as f:parsed=list(csv.DictReader(f))
    assert [r['代码'] for r in parsed]==[r['code'] for r in expected]
    for actual,wanted in zip(parsed,expected):
        assert actual['复核日期']=='2026-10-12' and actual['页面数据版本']==live['generation']
        assert json.loads(actual['完整收盘依据'])==wanted
    proof['csv'][name]=dict(rows=len(parsed),event_count=sum(r['event_count'] for r in expected),same_order=True,full_evidence_equals_disk=True)
with (ROOT/'output/playwright/radar-repair/current.csv').open(encoding='utf-8-sig',newline='') as f:parsed=list(csv.DictReader(f))
assert [r['代码'] for r in parsed]==live['current']==model['lists']['current']+model['lists']['limited']
for actual in parsed:
    assert actual['雷达数据版本']==live['generation']
    assert json.loads(actual['雷达事件与完整依据'])==rows[actual['代码']]['radar_opportunity']
proof['csv']['current.csv']=dict(rows=len(parsed),same_order=True,full_evidence_equals_disk=True)
(OUT/'page_detail_csv_consistency.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'browser_stage_evidence.json').write_text(json.dumps(stages,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'browser_live_evidence.json').write_text(json.dumps({k:v for k,v in live.items() if k not in ('close','detail','close_detail_html')},ensure_ascii=False,indent=2),encoding='utf-8')

changes=[];(OUT/'diffs').mkdir(exist_ok=True)
files=['radar_opportunity.py','radar_ui.js','dashboard_template.html','serve.py','check_live_service.py','test_radar_opportunity.py','test_radar_acceptance.py']
for name in files:
    old=OUT/'before'/name;new=ROOT/name
    before=old.read_text(encoding='utf-8-sig') if old.exists() else ''
    after=new.read_text(encoding='utf-8-sig')
    if before==after:continue
    (OUT/'diffs'/(name+'.diff')).write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='before/'+name,tofile=name)),encoding='utf-8')
    changes.append(dict(file=name,operation='修改' if old.exists() else '新增',before_sha256=hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,after_sha256=hashlib.sha256(new.read_bytes()).hexdigest()))
(OUT/'changed_files.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
assert json.loads(json.dumps(config.RADAR_OPPORTUNITY))==read('before/radar_opportunity_v1/rules_frozen.json')['parameters']

def link(name,label=None):return '['+(label or name)+']('+str(OUT/name).replace('\\','/')+')'
reset=read('reset_summary.json');frozen=read('frozen_compare.json');status=receipt['after']
lines=['# 雷达V1四项返工：修复与复验材料','',
'本材料提交复验，不把测试通过等同于用户验收通过。机会规则版本仍为 `'+ro.VERSION+'`；实施修复标识 `'+ro.REPAIR_VERSION+'`。RADAR_OPPORTUNITY及原评分/档位/分类/股票池/五分钟频率均未调参。','',
'## 1. 四项结果','',
'1. 后端输出阶段默认视图：竞价优先预警，收盘默认注明日期的收盘复核；盘前/非交易日为日线背景。用户手选视图仍保留，未手选时随数据阶段切换。非连续竞价空池解释“尚未进入确认时段”，不把尚未采样说成没有合格股票。','',
'2. fmt/sgn/pct先检查null/undefined/空字符串；未知显示“—”，真实数值0仍显示0。竞价M0/E0/进攻分的真实null未改成数值。未启用基准明确说明；竞价覆盖尚未核验记null，详情不报0%覆盖失败。','',
'3. 新增“收盘复核 · 2026-10-12”入口：直接展示112项收盘确认事件、92只去重股票；同股类别合并一行，保留日期、事件数、收益及全部原事件依据。支持类别筛选、详情、独立收盘CSV。61项收盘未确认对应55只股票，与确认股票存在重叠，不把两组去重数相加。历史来自原真实发布快照，仅投影，不用今日行情/成员重算。','',
'4. 14:38骤降属于旧实现的连续性判断缺陷，不是正常名单波动。旧代码以sequence.last_at检查600秒，却在已确认维持分支不推进该值；有效维持报价的last_source_at已推进而没有被该判断使用。14:39已补为last_source_at，但上一轮交付未披露异常及补丁依据。本轮复现该时间序列、保留600秒上限，并补齐未来逐轮sequence/continuity/reset_reason/代码哈希记录。','',
'## 2. 昨日状态变化依据','',
'| 生成时间（2026-10-12） | 主板源报价范围 | 当前 | 受限 | 待确认 |','|---|---|---:|---:|---:|',
'| 14:28:08 | 14:25:51—14:26:40 | 77 | 4 | 5 |',
'| 14:35:45 | 14:32:57—14:33:51 | 78 | 4 | 5 |',
'| 14:38:23 | 14:36:33—14:37:04 | 1 | 0 | 84 |',
'| 14:48:59 | 14:45:57—14:46:39 | 79 | 4 | 9 |','',
'以上为逐轮真实日志，不用页面刷新时间推定报价时间。逐轮记录 '+link('yesterday_rounds.json')+'；77只退出股票涉及92项上一轮已确认事件的逐事件表 '+link('reset_per_event.csv')+'；原始转换对象 '+link('reset_event_evidence.json')+'。源日志原样保存在before/radar_opportunity_v1/2026-10-12.jsonl。','',
'这92项事件真实相邻报价间隔192—222秒，过时正式样本间隔621—630秒。88项被退回待确认；3项进攻暂停包含真实开盘价失守，不能都归为误重置；1项降到正式涨幅门槛以下变为突破预警，原维持资格应独立检查。原事件ID和首次确认时间均未重写。','',
'代表：000498突破/持续事件，14:33:27→14:36:57实际210秒；旧样本停在14:26:36，误算621秒。原ID bd6f7800d549546faeae2fb2不变，却被重置为1次/0秒。'+link('reset_summary.json')+'。','',
'代码变更工具回执：初始错误分支13:50:05，替换为last_source_at的补丁14:39:00（北京时间）；'+link('prior_implementation_evidence.json')+'。回执证明代码修改时间，业务状态以真实journal为准。旧日志没有逐轮完整采样/实现哈希字段，因此不编造当时未记录的完整环境或部署哈希；现保存原始日志、补丁回执与可核验报价。','',
'回归采用000498的14:17:15、14:26:36、14:33:27、14:36:57源时间序列，在满足正式/维持条件的冻结测试输入上验证确认不误重置、事件ID/首次时间不变；真实相邻601秒仍必须重新确认。原既有维持降速测试也继续通过。','',
'## 3. 收盘名单来源与一致性','',
'真实来源及哈希 '+link('yesterday_close_record.json')+'。原data_version `1791797743095103900`，generation `536753b606b53689757b3f46`，保存112/92原结果及173项完整分类复核。迁移脚本 '+link('migrate_close_record.py')+' 只投影原结果，日期日线、平台与资格不重算。持久文件 `cache/radar_opportunity_v1/close_reviews/2026-10-12.json`；每天真实收盘复核到齐后原子保存，离线页面不调用采样或历史追加。','',
'实际浏览器下载：[92只完整收盘CSV](D:/股票强势监测/output/playwright/radar-repair/close.csv)、[持续进攻筛选CSV](D:/股票强势监测/output/playwright/radar-repair/close-sustained.csv)、[当前CSV](D:/股票强势监测/output/playwright/radar-repair/current.csv)。页面/详情/CSV比较原始JSON对象、日期、代码及顺序：'+link('page_detail_csv_consistency.json')+'。','',
'## 4. 测试与真实发布','',
'最终完整回归546项通过 '+link('full_tests.txt')+'；专项64项通过 '+link('special_tests.txt')+'；'+link('dashboard_check.txt')+'、'+link('live_check.txt')+' 通过。首次专项有1项当前类别默认初始化断言失败，已修正effective view并全量重验；原失败日志 '+link('first_special_failure.txt')+' 保留。补证还发现来源纳秒版本号超过JS精确整数范围，浏览器丢低位；改为字符串并重新真实发布后逐对象一致。'+link('metadata_precision_fix.json')+'。','',
'同一冻结输入：原快照逐字段相同、机会名单及全部参数相同；新增同日收盘档案不得穿越到收盘前冻结重放。'+link('frozen_compare.json')+'，计算约'+str(round(frozen['seconds'],2))+'秒。','',
'服务重启并POST /__refresh：`'+str(receipt['before']['data_version'])+'`→`'+str(status['data_version'])+'`；generation `'+status['ui_generation']+'`；实际发布 '+status['last_scan']+'。运行/磁盘hash `'+ro.IMPLEMENTATION_HASH+'`；修复标识已在/__status和快照核验。'+link('published_refresh.json')+'、'+link('published_refresh_snapshot.json.gz')+'。','',
'真实HTTP页面截图：[实时收盘名单](D:/股票强势监测/output/playwright/radar-repair/live-yesterday-close-http.png)、[实时收盘详情](D:/股票强势监测/output/playwright/radar-repair/live-close-detail-http.png)、[实时当前名单](D:/股票强势监测/output/playwright/radar-repair/live-current-http.png)。竞价与收盘默认阶段截图使用实际保存的真实输入，经当前修复代码生成HTTP冻结投影：[竞价预警/空值](D:/股票强势监测/output/playwright/radar-repair/auction-default-http.png)、[非连续竞价空池](D:/股票强势监测/output/playwright/radar-repair/auction-current-empty-http.png)、[收盘默认](D:/股票强势监测/output/playwright/radar-repair/close-default-http.png)。页面顶端明确写明冻结源时刻，不冒充当前实时阶段。','',
'## 5. 备份、差异与恢复','',
'基线源码/快照/事件/逐轮及发布日志/原冻结配置：'+link('before','before/')+'，'+link('baseline_manifest.json')+'。逐文件差异 '+link('diffs','diffs/')+'，'+link('changed_files.json')+'。新增加test_radar_acceptance.py，其余为已有文件的修复。','',
'恢复须先等服务扫描及发布空闲，设置cache/serve.stop并停止经身份核验的本项目PID；先归档当前源码、快照及radar_opportunity_v1目录，再恢复before内本轮修改的源码、snapshot.json和冻结配置，移出新增测试文件，按项目原方式重建页面、隐藏重启并真实刷新。完整实施前事件state及journal已备份；回退事件基线会放弃本轮后新增事件，须先保留其原样副本。本轮未实际回滚运行系统。','',
'仍有的证据边界：旧逐轮日志未保存每轮不变状态的完整sequence，状态变化表使用实际报价、已保存的转换事件及明确的代码回执；不据此捏造逐轮部署哈希。竞价/收盘边界在真实冻结输入上核验，实时核验发生于10月13日早盘；尚未声称今天实盘收盘结果。没有放宽600秒、没有回填成员、没有改股票池或阈值。']
(OUT/'四项返工复验交付.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
with config.pipeline_guard():
    lock=ro.directory()/'rules_frozen.json';record=json.loads(lock.read_text(encoding='utf-8'))
    record.setdefault('initial_implementation_hash',record['implementation_hash'])
    record.update(implementation_hash=ro.IMPLEMENTATION_HASH,accepted_data_version=status['data_version'],generation=status['ui_generation'])
    repair=dict(repair_version=ro.REPAIR_VERSION,at=status['time'],hash=ro.IMPLEMENTATION_HASH,evidence=str(OUT),parameters_unchanged=True)
    record.setdefault('repairs',[])
    if repair['hash'] not in [r['hash'] for r in record['repairs']]:record['repairs'].append(repair)
    config.atomic_write_text(lock,json.dumps(record,ensure_ascii=False,indent=2))
(OUT/'V1冻结修复记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(proof,ensure_ascii=False))
