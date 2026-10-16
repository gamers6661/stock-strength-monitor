import json,hashlib,difflib
from pathlib import Path
O=Path(__file__).parent;root=Path.cwd()
state=json.loads((O/'state_transitions.json').read_text('utf8'));fixture=json.loads((O/'fixture_verification.json').read_text('utf8'));live=json.loads((O/'live_verification.json').read_text('utf8'));post=json.loads((O/'post_publish_status.json').read_text('utf8'));pre=json.loads((O/'pre_refresh_status.json').read_text('utf-8-sig'))
assert post['data_version']!=pre['data_version'] and post['ui_generation']!=pre['ui_generation'] and post['refresh']['ok'] and not post['scan_active']
assert root.joinpath('config.py').read_bytes()==(O/'baseline/config.py').read_bytes()
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (O/'baseline').iterdir() if p.is_file()}
(O/'backup_manifest.json').write_text(json.dumps(manifest,indent=2),'utf8')
(O/'diffs').mkdir(exist_ok=True);changes=[]
for name in ('market_strength.py','test_market_strength_lunch.py'):
    p=root/name;b=O/'baseline'/name
    changes.append(dict(file=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    diff=''.join(difflib.unified_diff(b.read_text('utf8').splitlines(True) if b.exists() else [],p.read_text('utf8').splitlines(True),fromfile='before/'+name,tofile='after/'+name))
    (O/'diffs'/(name+'.diff')).write_text(diff,'utf8')
(O/'changed_files.json').write_text(json.dumps(changes,indent=2),'utf8')
lines=['# 午休衔接返工验收报告','','本轮仅修改market_strength.py的午休数据衔接，新增test_market_strength_lunch.py。config.py逐字节未变；模型版本继续为market-strength-2026-10-13.1。报价校验、分数、权重、尺度、强弱边界、成员覆盖、阶段/风险与采集周期不变，没有确认次数或等待流程。','','## 行为与来源','','上午有效批次保存完整原始报价，包括无成交记录、OHLC、昨收、有效限制、量额和价格口径来源，并保留原计算时点及风险观测。无成交原始记录保留是为了维持板块原有分母和覆盖依据，不会让无成交股票获得有效分数。','',
'午休新报价缺失、时间不合法或无法计算时，使用同日最后有效上午批次整体重算；股票、板块/题材、阶段、成员及后端排序来自同一批次，不混用非法午休价格。沿用原时点标记“午休参考”，刷新判断时间单独保留。连续午休刷新不推进来源时间。版本变化时同样从完整原报价重算，不相信旧版本分数；只有price/change_pct的边界表不能恢复参考。没有有效上午输入时仍显示未知。','',
'13:00以后不走午休沿用分支：有效午后报价第一轮即计算并替换；缺失、过期或上午旧报价不进入当前名单。当天上午输入的保存不参与任何午后准入。','','## 连续状态与冻结复算','','新增16项测试，原50项加新增16项共66项专项通过；完整回归553项通过（focused_tests.txt、regression.txt）。包括上午有效→午休非法/缺报价、无法计算、连续刷新、部分批次不可用、无成交分母、运行版本变化、完整旧快照恢复、价格边界表不足、隔日不沿用、午后合法替换和午后缺报价不入选。','',
'原冻结输入3120只股票、539个板块/题材的完整计算仍与原comparison.json一致。以该输入模拟非法12:30报价与后续缺报价：午休保留511只股票、16个板块；原始源时间 '+state['source_at']+'，原评价时点 '+state['evaluation_at']+'；连续刷新保持。正常13:05源报价立即作为连续竞价新结果；13:05缺报价时两轴不可用、股票与板块focus均为0。四类场景见state_transitions.json。模拟13:05沿用的是同份冻结价格，仅验证衔接，不声称是真实13:05行情。','',
'午休保留后，'+str(fixture['effective_stock_models_unchanged'])+'只有效个股完整模型（含阶段、原因、风险）及全部539个板块完整依据与上午一致，仅增加午休参考/原时间标记。特别核对无成交记录对expected/coverage的影响，未改变原成员确认图。','','## 页面、详情、成员和CSV','','用明确标记“午休衔接验收，非当前实盘发布”的HTTP验收页验证保留结果，未激活或覆盖生产页面。UI版本 '+fixture['generation']+'；原时点 '+fixture['source_at']+'。实际点击题材和行业→全部成员→趋势/情绪筛选和排序→成员详情→清除恢复3120全池，结果及顺序与同版后端一致。','',
'实际浏览器下载午休参考CSV：股票511行与同版HTTP逐字节相等；行业13行、题材3行分别在打开0、1、3个详情后的文件逐字节一致，并与HTTP导出一致。每行完整模型、原时间、午休参考标记和后端对象相等（fixture_verification.json、browser/）。上一轮三个修复未修改。','','## 实际发布','','最终PID '+str(live['pid'])+'；运行/快照/本地实现哈希均为 `'+live['implementation_hash']+'`。正常POST /__refresh返回started/quick；最后ready、last_scan_ok/last_publish_ok/refresh.ok均为true。data_version从 '+str(pre['data_version'])+' 更新为 '+str(post['data_version'])+'；UI generation更新为 '+live['ui_generation']+'。','',
'实际发布为午后采集 '+live['source_at']+'，当前强势 '+str(live['counts']['focus'])+' 只、板块/题材 '+str(live['board_counts']['focus'])+' 个。实盘详情、股票与两类板块CSV同版完整依据核对通过（live_verification.json）。这是发布时点结果，不要求保持负责人13:00样本的545/19数量。页面及服务检查通过（dashboard_check.txt、live_service_check.txt）。','',
'返工前源文件、配置、页面、快照与服务状态在baseline；backup_manifest.json、changed_files.json、diffs/记录备份与仅两项源码/测试改动。原备份、冻结输入和负责人报告未覆盖。','',
'![午休参考成员详情](browser/theme-member-detail.png)','','![午休参考雷达](browser/radar.png)']
(O/'午休衔接验收报告.md').write_text('\n'.join(lines)+'\n','utf8')
print('Report saved with continuous-state, original-source and release evidence.')
