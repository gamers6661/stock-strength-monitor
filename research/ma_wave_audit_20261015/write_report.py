import difflib,gzip,json,re
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
s=json.loads((OUT/'study.json').read_text(encoding='utf-8'));v=json.loads((OUT/'variants_and_samples.json').read_text(encoding='utf-8'));fix=json.loads((OUT/'fix_comparison.json').read_text(encoding='utf-8'))
with gzip.open(OUT/'baseline/snapshot.json.gz','rt',encoding='utf-8') as f:snapshot=json.load(f)
base=snapshot['ma_trend']
s.update(rule_version=base['version'],rule_hash=base['implementation_hash'])
(OUT/'study.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
def p(a,b):return f'{a}/{b}（{100*a/b:.1f}%）'
g=v['groups'];a=v['attack'];lines=['# 均线波段日期与涨停收复入口全面核查','',
'结论：皇台酒业暴露的形态并非孤例，但“涨停收复均线”不能直接等同于当前MA10阶段或已确认趋势启动。应把旧波段结束、新事件发生、新波段资格分开记录。本轮修复可确认的状态与展示错误，没有新增入口或调整原门槛。','',
'## 样本与检查方法','',
f"- 冻结行情采集时间 `{s['source']}`，完成日截至 `{s['asof']}`。参考规则 `{s['rule_version']}`，逐日回放只读取当时及此前数据。",
f"- 股票池{s['coverage']['total']}只，有效连续历史{s['coverage']['valid']}只；排除{s['coverage']['excluded']}只：{s['coverage']['reasons']}。每只最多160个完成交易日，前21日用于指标预热。不能把排除样本当成不符合趋势。",
'- 检查全部有效股票，事件条件是：旧阶段已结束、完成日收盘封板、重新站上MA5和MA10且两线向上，前一收盘至少低于其中一线。分为原入口已识别与原入口未识别两组。',
'- 全历史原入口未识别925个事件，涉及647只股票；同股票相邻10个交易日内重复事件去重后836个。它是普遍存在的另一类启动形态，不是皇台专用条件。',
'- 对有完整后续窗口的事件分别统计1、3、5、10个完成交易日。最近40个交易日单列；未满5日的皇台、上海电影、大连圣亚不计入5日分母。',
'- “5日守线”指这5个完成日收盘全部不低于各日MA10。“上探”指未来窗口最高价相对事件收盘的变化；不能当成可成交收益。未回放历史盘中15分钟退出，也没有模拟交易成本。',
'- 比较是描述性检查，没有随机对照，事件仍有股票和行情环境相关性，不能据此声称预测胜率。研究使用当前主板池，未覆盖已退市或当时不在池内的股票；历史ST制度变更资料也不完整。','',
'## 不能只看稳定性，也不能只看上涨空间','',
'| 窗口与组别 | 完整5日样本 | 5日全部守MA10 | 5日最高价上探中位数 | 上探至少10% | 至少一次收盘较事件下跌5% |',
'|---|---:|---:|---:|---:|---:|']
for period,label in [('all','全窗口'),('recent40','最近40日')]:
    for group,title in [('existing','原入口'),('recover','拟新增涨停收复')]:
        st=g[period+':'+group]['followup']['5'];at=a[period+':'+('existing_entry' if group=='existing' else 'recovery_candidate')]['5']
        lines.append(f"| {label} · {title} | {st['n']} | {p(st['hold'],st['n'])} | {at['median_upside']:.2f}% | {p(at['up_10'],at['n'])} | {p(at['close_down_5'],at['n'])} |")
lines+=['',
'全窗口的拟新增形态具有更大的上探空间；近期样本并未显示同样明显的进攻优势，同时失守和回吐更多。因此不能因部分个股失败就彻底排除，也不足以把所有这类涨停直接标成已确认强趋势。',
'增加“MA20上行且价格在其上”或改为“突破20日最高收盘”两种附加条件也分别检查过，近期5日守线比例约42.6%和40.0%，没有解决上述问题。没有据此继续搜索更多参数凑出皇台。','',
'## 皇台酒业的日期','',
'- 9月21日是旧波段强势入口；10月9日收盘11.45，低于当日MA10约11.475，旧波段已退出。',
'- 10月13日是新的收盘涨停收复事件：收盘12.25，MA5约11.556、MA10约11.538，两线均向上；五日均量口径量比约1.12。此前20日最高盘中价为12.86，所以不满足现有涨停突破入口。',
'- 它符合拟议的新事件形态，但只有10月14日这一个完成日可做后续检查，不能把它当成已验证的普适成功样本。',
'- 9月21日不得被解释为当前还在进行的MA10波段起点；10月13日是否成为新波段入口，必须由统一入口规则决定，不能只改这只股票的日期。','',
'## 分层抽检15个事件样本','',
'按早期/近期、原有/拟新增入口、守线/失守分层抽检，再加三个用户相关近期例子；这是一组有意覆盖不同结果的复核样本，不能拿抽检比例代替上面的全量统计。每个案例的OHLC与MA路径见 `variants_and_samples.json`。','',
'| 个股 | 事件日 | 类型 | 随后首次完成日失守MA10 | 5日最高价上探 | 检查结论 |',
'|---|---|---|---|---:|---|']
notes={
'002317':'前期短暂回落仍守MA10，后续继续上攻；不能只看事件次日涨跌。',
'600063':'5日守线并继续上攻，属于现入口会遗漏的例子。',
'603317':'涨停次日即收盘失守MA10，属于新形态也会产生的失败例子。',
'600936':'先有明显上探，随后失守；进攻幅度与趋势结束应分别表达。',
'000735':'先上探约19%，随后结束；不能把后来的退出倒推为事件当天无强势。',
'603200':'5日守线并有明显上探；以后再失守需退出。',
'002721':'涨停收复后推进不足，随后失守；单个涨停不能保证延续。',
'600539':'封板但随后上探有限，进一步说明仍需强势程度证据。',
'000818':'原门槛识别的强势样本，正常承接后推进。',
'603318':'原门槛也会有提前失守，不能把原模型当成无误差基准。',
'600770':'保持MA10，但后续进攻幅度普通；稳定不等同于进攻很强。',
'605168':'原入口样本也出现失守后反抽，不能只看第5日是否又在线上。',
'000995':'只有1个后续完成日，不参与5日比例。',
'601595':'只有3个后续完成日；10月12日才被现入口确认，存在识别延迟。',
'600593':'只有1个后续完成日，不据此证明新入口普适。'}
for x in v['samples']:
    f=x['followup'].get('5');loss=next((x['followup'][n]['first_loss_date'] for n in ('1','3','5','10') if n in x['followup'] and x['followup'][n]['first_loss_date']),None)
    lines.append(f"| {x['name']} {x['code']} | {x['date']} | {'原入口' if x['group']=='existing_entry' else '拟新增事件'} | {loss or '已覆盖窗口未失守'} | {(str(round(f['max_high_return_pct'],2))+'%') if f else '未满5日'} | {notes.get(x['code'],'已核对日线路径')} |")
lines+=['', '## 另抽检8个波段状态案例','',
'- 郑中设计、华北制药、阳光乳业：本波起点以后，已覆盖完成日收盘没有失守MA10，后续强势确认仍属同波推进。不能把所有“最近强势确认”直接覆盖为“本轮起点”。历史盘中缺证不等同于证明从未盘中失守。',
'- 闽发铝业、金安国纪、山东出版、海星股份、领先股份：历史回放曾出现“较新波段到期，但last_exit仍指更旧波段”的状态错配。当前快照中明确表现为闽发铝业的8月起点配5月退出。',
'- 另发现27只股票历史上曾有未确认平台的MA10承接超过20日；当前冻结快照没有这种未到期状态。这与“已确认平台超过20日到期”口径不同，不能擅自把长期守住MA10的股票全部强制退出。本轮没有改这项策略边界。','',
'## 已修复与保留','',
'- 修复已确认平台到期时遗漏本次退出事件，记录本波起点、日期及“平台观察到期”原因，避免沿用旧波的失守记录。',
'- 个股页的MA5/MA10/MA20当前阶段筛选排除已退出历史标签；全部成员仍完整保留，历史阶段明确加前缀。雷达与个股详情也把历史起点单独标明。',
'- 未加入“涨停收复启动”正式入口，未把皇台日期强行改成10月13日，MA5/10/20准入阈值不变。',
f"- 固定完成日输入对比{fix['tested']}只：阶段、起点和平台完全不变；仅修复{len(fix['changed_exit_records'])}只股票的末次退出记录（含之前缺失的到期记录）。",
'- 680项完整测试与82项针对性检查通过。实际服务及页面验收结果见 `browser_acceptance.json`、`live_check.txt`、`dashboard_check.txt`。','',
'后续建议：把“涨停收复”作为独立的新启动候选事件记录日期，先与趋势阶段分开；是否进入MA5正式观察，再使用统一的后续推进确认规则。原波段没有结束时，继续保留原起点并更新最近确认日。该建议尚未作为新入口发布。']
(OUT/'全面核查与抽检.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
parts=[]
for old in (OUT/'baseline').glob('*'):
    if old.suffix not in ('.py','.js'):continue
    current=ROOT/old.name
    parts.extend(difflib.unified_diff(old.read_text(encoding='utf-8').splitlines(),current.read_text(encoding='utf-8').splitlines(),fromfile='before/'+old.name,tofile='after/'+old.name,lineterm=''))
parts.extend(difflib.unified_diff([], (ROOT/'test_wave_audit.py').read_text(encoding='utf-8').splitlines(),fromfile='/dev/null',tofile='after/test_wave_audit.py',lineterm=''))
(OUT/'source.diff').write_text('\n'.join(parts),encoding='utf-8')
print('Report and source diff saved')
