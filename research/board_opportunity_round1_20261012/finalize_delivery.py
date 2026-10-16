# -*- coding: utf-8 -*-
"""汇总可复核交付，不调用扫描或机会计算。"""
import csv
import difflib
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
import config
import board_opportunity as B

def read(name):return json.loads((HERE/name).read_text(encoding='utf-8-sig'))
def zipped(name):
    with gzip.open(HERE/name,'rt',encoding='utf-8') as f:return json.load(f)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def link(name,label=None):return f'[{label or name}]({(HERE/name).as_posix()})'
def num(v):return 'null' if v is None else f'{v:.6f}' if isinstance(v,float) else str(v)
def checks(o):return json.dumps(o['failed_reasons'],ensure_ascii=False,separators=(',',':'))

files={
 'config.py':'集中固定阈值，原有评分与刷新参数不变。',
 'board_opportunity.py':'新增成员聚合、指标、资格、源时间确认、背景、真实日线记录、统一排序和只读验算。',
 'scoring.py':'行情缺失及 attack_model 处理后、写盘前接入；竞价入口只生成观察与日线背景。',
 'board_center.py':'增加可选 member_pool，沿用同花顺映射；本轮缺失报价仍进入应统计成员分母。',
 'board_trend.py':'给原 replay 增加可选只读 observer，保留同一趋势段真实回踩痕迹；原状态输出不变。',
 'dashboard_template.html':'增加六个机会入口、成员指标卡片、独立指数展示、资格详情和同结果 JSON 导出；机会固定排序。',
 'make_dashboard.py':'传递机会版本；已有机会结果时只投影，离线不重评指数、不推进机会。',
 'serve.py':'公开代码／快照机会版本及数量，启动时检查模型版本一致。',
 'check_live_service.py':'核验新版本、数量、公式及完整／摘要／压缩／详情链路一致。',
 'check_dashboard.py':'校验页面与磁盘机会结果一致并验算输出。',
 'test_board_opportunity.py':'40 项业务边界、状态、数据链路与冻结输入专项测试。',
}
after=HERE/'after';after.mkdir(exist_ok=True)
manifest={};diffs=[]
for name,note in files.items():
    source=ROOT/name;before=HERE/'before'/name
    original=before.read_text(encoding='utf-8') if before.exists() else ''
    actual=source.read_text(encoding='utf-8')
    assert actual!=original,name+' 无差异'
    manifest[name]={'before_sha256':sha(before) if before.exists() else None,'after_sha256':sha(source),
                    'backup':before.as_posix() if before.exists() else None,'new_file':not before.exists(),'change':note}
    diffs.extend(difflib.unified_diff(original.splitlines(keepends=True),actual.splitlines(keepends=True),
                                    fromfile='before/'+name if before.exists() else '/dev/null',tofile=name))
    shutil.copy2(source,after/name)
(HERE/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'changes.diff').write_text(''.join(diffs),encoding='utf-8')

original=read('before/snapshot.json');frozen=read('frozen_after.json');comparison=read('frozen_comparison.json')
live=read('live_evidence.json');status=read('refresh_final_status.json');accepted=zipped('accepted_snapshot.json.gz')
browser=read('browser_evidence.json');web=zipped('browser_snapshot.json.gz');offline=read('offline_evidence.json')
lunch=read('lunch_evidence.json')
assert live['http_disk_equal'] and browser['export_equal'] and not browser['errors']
assert live['before_data_version']!=live['after_data_version']
assert comparison['all_existing_fields_identical'] and offline['confirmation_unchanged'] and offline['daily_files_unchanged']
assert status['code_board_opportunity_version']==status['snapshot_board_opportunity_version']==B.VERSION
assert 'OK' in (HERE/'check_dashboard.txt').read_text(encoding='utf-8-sig')
assert 'OK pid=' in (HERE/'check_live_service.txt').read_text(encoding='utf-8-sig')
full=(HERE/'full_tests_final.txt').read_text(encoding='utf-8-sig')
special=(HERE/'special_tests.txt').read_text(encoding='utf-8-sig')
assert re.search(r'Ran 488 tests.*\n\s*\nOK',full)
assert re.search(r'Ran 40 tests.*\n\s*\nOK',special)
old_by={b['id']:b for b in original['board_catalog']}
frozen_by={b['id']:b for b in frozen['board_catalog']}
manual_by={b['id']:b for b in accepted['board_catalog']}
by={b['id']:b for b in web['board_catalog']}
assert set(by)==set(old_by)==set(frozen_by)==set(manual_by)

rows=[]
for bid,b in by.items():
    old=old_by[bid];fo=frozen_by[bid]['opportunity'];mo=manual_by[bid]['opportunity'];o=b['opportunity'];d=o['daily'];q=o['current']
    idx=old.get('index_current') or {};row=dict(id=bid,type=b['type'],name=b['name'],
       before_at=original['generated_at'],before_index_state=idx.get('state'),
       before_index_watch=bool(old.get('ranking_eligible') and idx.get('ready') and idx.get('priority_observation')),
       before_opportunity='未启用',frozen_daily=fo['daily_mainline'],frozen_mainline=fo['qualifications']['mainline'],
       frozen_startup_raw=fo['startup_raw'],frozen_startup=fo['qualifications']['startup'],frozen_restart_raw=fo['restart_raw'],
       frozen_restart=fo['qualifications']['restart'],manual_at=accepted['generated_at'],manual_label=mo['primary_label'],
       manual_mainline=mo['qualifications']['mainline'],manual_startup=mo['qualifications']['startup'],manual_restart=mo['qualifications']['restart'],
       screenshot_at=web['generated_at'],version=o['version'],daily_asof=o['daily_asof'],current_judgment=o['judgment_at'],
       daily_mainline=o['daily_mainline'],current_mainline=o['current_mainline'],startup_raw=o['startup_raw'],restart_raw=o['restart_raw'],
       mainline=o['qualifications']['mainline'],startup=o['qualifications']['startup'],restart=o['qualifications']['restart'],
       label=o['primary_label'],status=o['status'],pending=o['pending'],verification_pending=o['verification_pending'],
       expected_count=o['expected_count'],excluded_count=o['excluded_count'],excluded=json.dumps(o['excluded'],ensure_ascii=False),
       daily_count=d['valid_count'],daily_cover=d['coverage_pct'],quote_count=q['valid_count'],quote_cover=q['coverage_pct'],
       event_valid_count=q['event_valid_count'],R5=d['R5'],E5=d['E5'],P5=d['P5'],T=d['T'],median5=d['median5'],
       trimmed_R5=d['trimmed_R5'],trimmed_E5=d['trimmed_E5'],R0=q['R0'],E0=q['E0'],U0=q['U0'],A0=q['A0'],B0=q['B0'],
       median0=q['median0'],trimmed_R0=q['trimmed_R0'],trimmed_E0=q['trimmed_E0'],earliest_source=q['sample_at'],latest_source=q['latest_quote_at'],
       startup_count=o['startup_confirmation']['count'],startup_span=o['startup_confirmation']['span_seconds'],
       startup_first=o['startup_confirmation']['first_confirmed_at'],restart_count=o['restart_confirmation']['count'],
       restart_span=o['restart_confirmation']['span_seconds'],restart_first=o['restart_confirmation']['first_confirmed_at'],
       background=o['background']['source'],background_reason=o['background']['reason'],episode=o['background']['episode_id'],
       pullback_start=o['background']['pullback_start'],index_divergence=o['index_member_divergence'],
       member_hash=o['members_hash'],reasons=checks(o))
    rows.append(row)
with (HERE/'实施前后板块资格变化.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

cases=[
 ('市场跌4%、板块跌1%','test_falling_market_outperformance_is_not_mainline'),
 ('趋势高、5日仅涨1.5%','test_high_trend_but_low_r5_not_mainline'),
 ('少数领先成员上涨、其余走弱','test_leaders_only_fail_trimmed_breadth'),
 ('昨天持续强势、今天走弱','test_daily_background_survives_current_failure'),
 ('指数强、主板成员未跟上','test_official_index_alone_cannot_qualify'),
 ('未形成完整多头、成员共同上涨','test_no_daily_multiline_requirement_for_startup'),
 ('重复源批刷新三次','test_duplicate_batch_does_not_confirm'),
 ('三轮但不足10分钟','test_three_samples_short_span_pending'),
 ('一轮失败／午休／跨日中断','test_failure_breaks_and_preserves_first_confirmation + test_lunch_retains_and_afternoon_restarts + test_day_version_members_and_long_gap_reset'),
 ('79.99%／80%原值判断','test_exact_coverage_boundary_without_rounding'),
 ('仅五只成员','test_five_members_never_form_qualification'),
 ('收益缺失、报价过期、趋势未知','test_missing_returns_stale_quotes_unknown_trend_not_zero'),
 ('回踩后同轮恢复推进、R5低于3%','test_pullback_recovery_preserves_segment_without_r5_floor'),
 ('无进攻背景的超跌反弹','test_no_background_rebound_and_post_pullback_attack_not_used'),
 ('旧事件、未知价格口径、严重风险','test_event_excludes_stale_unknown_basis_risk_and_restriction'),
 ('多资格去重与主标签优先','test_multiple_qualifications_dedup_and_priority'),
 ('离线生成不改变确认或历史','test_payload_summary_pack_details_and_offline_are_projection + offline_verify.py'),
 ('冻结输入旧评分／档位／名单／指数一致','test_frozen_input_preserves_stocks_members_and_index_fields + verify_frozen.py'),
]
record_folder=config.CACHE_DIR/'board_opportunity_daily'/B.VERSION
records=[]
for path in record_folder.glob('*.json'):
    item=json.loads(path.read_text(encoding='utf-8'));records.append({'file':path.as_posix(),'asof':item['asof'],'records':len(item['records']),'sha256':sha(path)})
    shutil.copy2(path,after/('daily_record_'+path.name))
(HERE/'daily_record_evidence.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

def case_text(bid):
    b=by[bid];o=b['opportunity'];d=o['daily'];q=o['current']
    s=f"**{b['name']}**：{o['status']}。日线 R5={num(d['R5'])}%，T={num(d['T'])}%；当前 R0={num(q['R0'])}%，E0={num(q['E0'])} 个百分点，U0={num(q['U0'])}%，报价 {q['valid_count']}/{o['expected_count']}，B0={num(q['B0'])}，剔除领先成员后 R0={num(q['trimmed_R0'])}%，E0={num(q['trimmed_E0'])} 个百分点。"
    if o['qualifications']['startup']:s+=f" 新启动 {o['startup_confirmation']['count']} 轮、{o['startup_confirmation']['span_seconds']} 秒，首次确认 {o['startup_confirmation']['first_confirmed_at']}。"
    elif o['startup_raw'] is True:s+=f" 新启动本轮条件满足，但当前连续序列仅 {o['startup_confirmation']['count']} 轮、{o['startup_confirmation']['span_seconds']} 秒，仍待确认；之前首次确认时间仅作留存，不延续有效标签。"
    if o['qualifications']['restart']:
        bg=o['background'];c=o['restart_confirmation']
        s+=f" 再启动 {c['count']} 轮、{c['span_seconds']} 秒，首次确认 {c['first_confirmed_at']}；背景仅为“{bg['source']}”，前期证据 {bg.get('evidence_asof')}（指数5日涨幅 {num(bg.get('evidence_ret5'))}%），回踩始于 {bg['pullback_start']}，段标识 {bg['episode_id']}。"
    return s

report=[f'# 板块机会第一轮实施与验收\n\n规则版本：`{B.VERSION}`。工作目录：`{ROOT}`。阈值按本轮指令固定，没有按当天名单调整。',
f'新增三类机会由后端统一计算，默认并集去重；主标签依次为回踩再启动、持续强势、新启动。手动刷新验收快照截至 **{accepted["generated_at"]}**，页面截图截至 **{web["generated_at"]}**，完成日线为 **{live["daily_asof"]}**。最终刷新与完整浏览器验证采用同一代次，另保存午休代次证据。',
'## 修改、备份与原规则保留',
f'修改前源文件、实际快照、股票池、服务状态和同批原始报价保存在 {link("before","before/ 备份目录")}；备份 SHA256 见 {link("before/manifest.json")}。新增文件原先不存在。最终源文件副本在 {link("after","after/ 交付副本")}。逐文件完整差异：{link("changes.diff")}；新旧哈希、备份位置：{link("source_manifest.json")}。',
'| 文件 | 实施内容 |\n|---|---|\n'+'\n'.join(f'| [{name}]({(ROOT/name).as_posix()}) | {note} |' for name,note in files.items()),
'必要扩展到 board_center.py、board_trend.py、make_dashboard.py、check_dashboard.py：分别保证缺失报价不缩分母、已修复回踩仍有真实记录、离线只投影、页面结果可验算。没有新增行情请求，也没有改个股评分、同花顺分类和黑名单、MA10/MA20支撑规则、成员7天更新或300秒刷新。observer 只观察原状态机，不改状态转换。',
'## 数据口径与公式',
'成员取已有 member_codes 去重，关联同一主板股票池、本轮报价、stocks 和 coverage_catalog。数据缺失、日线不足和过期报价保留在应统计分母；明确排除对象逐代码记录原因和数量。未评分但有效报价可参加纯价格统计，不能补成趋势或突破。日线日期须等于 strength_model.asof，趋势资格必须可核验；当前事件另须价格口径有效、形态为本轮、无严重风险和不可交易限制。缺失值留 null。',
'| 指标 | 公式／口径 |\n|---|---|\n| R5 / E5 | 日线有效 ret5 等权均值 / 减全体有效主板5日等权收益 |\n| P5 / T | ret5>0 比例 / 已核验趋势在线比例 |\n| R0 / E0 | 当前有效报价涨跌幅等权均值 / 减同批全体有效主板当日等权收益 |\n| U0 / A0 | 当日涨幅>0比例 / 当日涨幅≥3%数量 |\n| B0 | 当前有效事件的不同股票数，仅指定五种 live_attack_event |\n| 中位数 | 日线有效 ret5、有效当日涨跌幅分别计算 |\n| 剔除领先成员 | 6—9只剔除最高1只，≥10只剔除最高3只；剩余等权及减同周期市场基准 |',
'全部计算和资格判断使用未四舍五入原值。有效成员至少6只、对应覆盖至少80%；6—9只标小样本。主板基准每个代码只算一次，基准覆盖不足80%时相对资格待核验；不平均题材收益，也不将剔除结果描述为官方指数权重贡献。日线、报价、事件有效集合和源时间在输出中分开保存。',
'| 资格 | 固定条件 |\n|---|---|\n| 日线持续强势 | 有效≥6、覆盖≥80%、R5≥3%、E5≥2个百分点、P5≥60%、T≥max(25%,市场T+10个百分点)、剔除后R5>0且E5>0 |\n| 当前持续强势 | 日线资格成立；当前有效≥6、覆盖≥80%、R0>0、E0>0、U0≥50%、剔除后R0>0且E0>0 |\n| 新启动当轮 | 当前有效≥6、覆盖≥80%、R0≥1%、E0≥1个百分点、U0≥60%、A0≥3（6—9只要求≥2）、剔除后R0>0且E0>0 |\n| 回踩再启动当轮 | 背景成立、当前同名指数ready、现价≥滚动MA5/MA10、未转弱；当前有效≥6、覆盖≥80%、R0>0、E0>0、U0≥55%、剔除后R0>0且E0>0、B0≥2 |',
'回踩背景要求同名指数、原状态机同趋势段回踩记录，以及回踩前20个完成交易日内的真实 daily_mainline 记录或当时及以前完整6日窗口算出的指数5日涨幅≥5%。后者只标“指数历史进攻背景”。缺失或不足保持待核验，不用当前成员名单回填。趋势段结束或转弱清除；同段修复后仍保留背景；R5不设3%门槛。',
'## 确认与保存',
'样本时间是参与统计成员最早的有效源报价时间。新启动至少3轮且首末≥600秒；再启动至少2轮且≥300秒。时间必须推进，重复批次不增数，间隔>600秒、条件失效或数据不足中断。日期、成员名单哈希、独立规则版本变化重置；同版本重启可恢复但仍查连续性。失效退出当前资格，同日首次确认时间保留。',
'竞价只观察与展示日线背景；午休保留上午结果和对应市场基准、成员报价审计、截至时间，下午重新确认。收盘条件在 close_review 单列“收盘复核”，盘后重复采样不能补次数。页面及导出只读后端资格和排序（E0→U0→R0→有效报价数降序→名称），无人数上限。',
f'确认随快照保存，无新数据库。完成日线记录存于 `{record_folder}`，按日、版本、板块和成员哈希记录真实计算结果，旧口径不重写。实际记录文件：{link("daily_record_evidence.json")}；本轮仅首次计算了2026-10-09完成日线，没有回填此前强势池。',
'## 冻结输入对照与业务案例',
f'原冻结快照 {comparison["input_generated_at"]}，同批报价采集 {comparison["input_quote_capture_at"]}：{comparison["stock_rows"]} 个评分对象、{comparison["coverage_rows"]} 个覆盖对象、{comparison["board_rows"]} 个板块。新增字段剥除后完整快照深度相等，因此原评分、档位、成员和指数字段全部不变；450个可核验指数用修改前／后的 replay 对同一完成日线重放，输出逐项相等。摘要压缩后539个机会对象完整一致。',
f'结果：{link("frozen_comparison.json")}；可复跑脚本：{link("verify_frozen.py")}；冻结后完整输入：{link("frozen_after.json")}；539行冻结资格变化：{link("冻结输入资格变化.csv")}。冻结新增当前机会为0、日线背景23，不把随后确认或行情变化归因于公式修改。',
'| 验收场景 | 直接验证 | 结果 |\n|---|---|---|\n'+'\n'.join(f'| {label} | `{test}` | 通过 |' for label,test in cases),
'此外覆盖市场基准不足、6—9只A0≥2、10只剔除3只、日期／未来时间／批次偏差／无效OHLC、明确无成交排除、未评分价格参与、同版本恢复、倒退时间、真实记录不改写、指数转弱清除、当前指数未知、盘后报价不累计以及午休成员变化。',
'## 测试、页面与离线检查',
f'命令 `python -B -X utf8 -m unittest discover -p \'test_*.py\'`：**488项通过**（最终服务暂停扫描的互斥测试窗口）；专项40项通过。{link("full_tests_final.txt")} / {link("special_tests.txt")}。早先与在线扫描重叠的全套运行遇到 PipelineBusy，日志保留，未更改互斥保护；隔离后最终全套通过。',
f'`python -B -X utf8 check_dashboard.py` 与 `python -B -X utf8 check_live_service.py` 均通过：{link("check_dashboard.txt")} / {link("check_live_service.txt")}。核验规则版本、快照数量、公式、完整快照、摘要、gzip数据包和板块详情使用同结果。模板脚本另经 node --check。',
f'实际HTTP浏览器验证：`{browser["url"]}`，代次 `{browser["generation"]}`。行业／题材的六类入口卡片IDs与顺序逐一匹配后端；详情6张资格表；空结果；实际JSON下载{browser["export_rows"]}个板块的成员及机会对象逐项相等；JS页面错误0。{link("browser_evidence.json")}、{link("browser_board_export.json")}、{link("browser_snapshot.json.gz")}。',
f'离线生成2次、实际HTTP离线导出2次，确认次数和日线文件SHA256均不变，测试中禁止调用 enrich 和指数重评：{link("offline_evidence.json")} / {link("offline_verify.txt")}。离线检查首次与另一个页面检查的写锁重叠而中止，保留 {link("offline_lock_collision.txt")}，串行重跑通过，没有放宽互斥。',
f'另有实际午休验证：{lunch["snapshot_at"]}，539个板块的资格、确认、成员指标、背景、主板基准和报价审计全部与上一早盘采样相等，页面注明“午休保留上午结果”及源时间。{link("lunch_evidence.json")} / {link("browser_lunch_result.txt")}。竞价、下午重新确认与收盘边界由专项验证，尚无本轮当天收盘实盘结果。',
'## 上线刷新闭环',
f'按既有守护方式停止空闲旧进程、运行完整检查，再启动正式Pythonw服务；上线PID **{live["pid"]}**，`/__status` code/snapshot 均为 `{B.VERSION}`，phase=ready、scan/publish成功。最终状态：{link("refresh_final_status.json")}。',
f'真实 `POST /__refresh` 回执 `{json.dumps(live["receipt"],ensure_ascii=False)}`，等待扫描及发布完成：data_version **{live["before_data_version"]} → {live["after_data_version"]}**；generation `{live["before_generation"]} → {live["after_generation"]}`。重新读取实际HTTP页并解包，板块机会模型及每个机会对象与磁盘快照一致；验算通过。{link("refresh_receipt.json")} / {link("live_evidence.json")} / {link("accepted_snapshot.json.gz")} / {link("accepted_http.html.gz")}。',
'| 采样 | 当前去重 | 持续强势 | 新启动 | 回踩再启动 | 待确认／待核验 | 日线背景 |\n|---|---:|---:|---:|---:|---:|---:|\n'+'\n'.join('| '+label+' | '+' | '.join(str(counts[k]) for k in ('current','mainline','startup','restart','pending','daily'))+' |' for label,counts in [('冻结输入',comparison['counts']),('真实手动刷新 '+accepted['generated_at'],live['counts']),('实际页面 '+web['generated_at'],browser['counts'])]),
'单类数量可重叠，所以三类数量之和不等于去重机会数。以上时点持续强势当前资格为0，如实保留空列表；没有降低门槛。',
'## 每个板块变化与真实代表',
f'逐板块539行变化表：{link("实施前后板块资格变化.csv")}。包括原指数入口、同冻结输入新增资格、真实刷新资格、截图代次资格、指标／覆盖／排除／确认／背景／趋势段／所有未通过原因。原系统没有三类机会，实施前写“未启用”，不冒写为false。实时前后受行情和确认采样影响，单独列时点。',
case_text('industry:出版'),
case_text('industry:风电设备'),
case_text('industry:电池')+' 官方指数当前为强势推进，成员R0仍为负，页面明确标示指数与主板成员分歧；日线背景保留，当前机会退出。',
case_text('industry:国有大型银行Ⅱ')+' 尽管趋势在线比例高，R5不足3%；同时A0未达小样本2只要求，未入新启动。',
case_text('industry:化妆品'),
'## 实际HTTP截图',
'| 页面 | 截图 |\n|---|---|\n'+ '\n'.join(f'| {label} | {link("screenshots/"+name)} |' for label,name in [
 ('行业当前机会','industry-current.png'),('题材当前机会','theme-current.png'),
 ('行业持续强势（真实空）','industry-mainline.png'),('题材持续强势（真实空）','theme-mainline.png'),
 ('行业新启动','industry-startup.png'),('题材新启动','theme-startup.png'),
 ('行业回踩再启动','industry-restart.png'),('题材回踩再启动','theme-restart.png'),
 ('待确认／待核验','industry-pending.png'),('日线强势背景','industry-daily.png'),
 ('新启动详情与依据','detail-overview.png'),('回踩真实详情','real-restart.png'),
 ('回踩完整资格依据','real-restart-evidence.png'),('日线背景与指数分歧','real-daily-divergence.png'),
 ('空搜索结果','empty-search.png'),('实际午休保留与截至时间','lunch-current.png')]),
'详情逐表截图：'+ '、'.join(link(f'screenshots/detail-criteria-{i}.png',f'资格表{i+1}') for i in range(6))+'。',
]
(HERE/'验收报告.md').write_text('\n\n'.join(report)+'\n',encoding='utf-8')
print(json.dumps({'source_files':len(files),'boards':len(rows),'version':B.VERSION,'report':(HERE/'验收报告.md').as_posix(),'counts':browser['counts']},ensure_ascii=False))
