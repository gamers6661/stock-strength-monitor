import json,sys,time,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));import config
OUT=Path(__file__).parent;deadline=time.monotonic()+600
while time.monotonic()<deadline:
    status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status',timeout=15))
    s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
    if status.get('last_scan_ok') and s.get('session') in ('早盘','午盘','尾盘') and str(s.get('quote_capture_at','')).startswith('2026-10-16') and str(s['quote_capture_at'])[11:16]>='09:30':break
    time.sleep(10)
else:raise TimeoutError('Opening publication has not completed')
for name,script in [('live_service','check_live_service.py'),('dashboard_check','check_dashboard.py')]:
    with (OUT/(name+'.txt')).open('w',encoding='utf-8') as f:
        r=subprocess.run([sys.executable,'-X','utf8',script],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    assert r.returncode==0,(name,(OUT/(name+'.txt')).read_text(encoding='utf-8')[-1500:])
from collections import Counter
status=json.load(urllib.request.urlopen('http://127.0.0.1:8848/__status',timeout=15))
s=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
result=dict(pid=status['pid'],generation=status['ui_generation'],session=s['session'],capture=s['quote_capture_at'],
    source=(s.get('market_strength') or {}).get('source_at'),coverage=s['market_strength']['coverage'],
    ma_counts=s['ma_trend']['counts'],ma_pending=Counter(r['ma_trend']['reason'] for r in s['stocks']+s.get('coverage_catalog',[]) if r['ma_trend']['pending']),
    performance=status.get('last_pipeline_performance'),checks=['check_live_service.py','check_dashboard.py'])
(OUT/'opening_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
report='''# 修复与验收记录

已完成10月15日接续关系、历史停牌与K线工作的发布，并按10月16日要求调整成交量单位和盘前启动。

- 接续及伴生只接受共同主营行业，或双方均有来源和业务依据的主线概念。冰山冷热与新华传媒、百洋股份的错误关系已移除；慈文传媒与新华传媒保留传媒主营行业依据。
- 成交量展示、K线悬停和CSV使用万股；成交额及封单金额使用亿元。内部原始单位保留，导出换算已逐值核对。
- 历史缺口按指定停牌规则标注，不补造蜡烛；新华传媒保留至10月12日真实K线，公告核验日期与缺失推定日期分别显示。7根、15根短历史能正常画图，未形成的均线周期留空。
- 同批其他股票有效时，对缺失或过期股票单独重试；仍不可用按停牌推定，复牌后继续。全源失败、竞价报价及未来报价不作为正常成交对照。
- 09:10盘前不再把DataNotReady当作初始化错误；使用上一完成日数据。模型有更新时按本地完成日和原始收市记录重算，保留原始报价时间。竞价报价独立展示，趋势与接力保留完成日参考；正式开盘后恢复正常计算。
- 修复短历史MA20空值引发的整轮竞价异常，并在所有成员投影结束后重新同步竞价明细。

## 验证

817项测试通过。真实浏览器已核对情绪关系、金额单位、3只股票的蜡烛图及悬停、停牌说明和CSV，没有页面脚本异常。正式开盘后的第一轮自动刷新已通过服务与页面检查。

原始冻结对比见前一目录mainline_gap_policy_20261015/frozen_comparison.json：原始报价、历史K线、板块成员不变；历史缺口按有效成交日核算后，10月15日合格均线观察由117只变为122只，MA20仍为0，数值门槛未放宽。

本目录live_acceptance.json保留竞价及完成日参考核对，opening_acceptance.json保留正式开盘验证；browser_acceptance.txt、情绪核对.csv、full_tests.txt和combined_source_changes.diff分别保存页面、导出、测试和完整改动证据。
'''
(OUT/'修复验收.md').write_text(report+'\n正式开盘发布：'+json.dumps({k:v for k,v in result.items() if k not in ('performance','ma_pending')},ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
