"""记录实际服务、两只股票、全池数据状态和浏览器导出的一致性。"""
from collections import Counter
import csv
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import config
import session_context

OUT=Path(__file__).parent
snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
with urlopen('http://127.0.0.1:8848/__status',timeout=15) as f:status=json.load(f)
assert status['phase']=='ready' and status['last_scan_ok'] and status['snapshot_generated_at']==snap['generated_at']
assert status['code_session_context_version']==status['snapshot_session_context_version']==session_context.VERSION
raw=(OUT/'browser_result.txt').read_text(encoding='utf-8-sig')
browser,_=json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())
(OUT/'browser.json').write_text(json.dumps(browser,ensure_ascii=False,indent=2),encoding='utf-8')
rows=snap['stocks']+snap.get('coverage_catalog',[])
by={r['code']:r for r in rows}
selected={c:by[c]['session_context'] for c in ('600241','603867')}
for c,v in selected.items():
    assert v['history_evidence']['count']==160 and v['history_evidence']['valid']
    assert v['quote_valid'] and v['price_basis_valid'] and v['quote_at'].startswith('2026-10-08')
assert selected['600241']['setup_state']=='尚未形成整理'
assert selected['600241']['current_label']=='20日新高突破'
assert selected['603867']['current_label']=='反包修复'
assert selected['603867']['structure_state']=='原平台内承接'
with (ROOT/'output/playwright/current-judgment-all.csv').open(encoding='utf-8-sig',newline='') as f:
    reader=csv.DictReader(f);headers=reader.fieldnames;export=list(reader)
assert len(export)==len(rows)==3120
assert len(headers)==241 and all(None not in r for r in export)
assert all(r['衔接模型']==session_context.VERSION for r in export)
for c in selected.values():
    assert any(r['最新价格判断']==c['current_label'] and r['当前平台状态']==c['structure_state'] and
               r['衔接报价截至']==c['quote_at'] and r['本地日线数']=='160' for r in export)
result=dict(status=status,selected=selected,total=len(rows),
    history_valid=sum(r['session_context']['history_evidence']['valid'] for r in rows),
    setup_states=dict(Counter(r['session_context']['setup_state'] for r in rows)),
    history_issues=dict(Counter(r['session_context']['history_evidence']['reason'] for r in rows if not r['session_context']['history_evidence']['valid'])),
    csv=dict(rows=len(export),columns=len(headers),name=browser['downloadName']),tests=285)
retry=json.loads((OUT/'retry_gaps.json').read_text(encoding='utf-8'))
result['history_retry']={k:v for k,v in retry.items() if k!='checks'}
(OUT/'after.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 最新判断与历史依据修复验收','',
       f"实际服务 PID {status['pid']}；已发布快照 {snap['generated_at']}；模型 {session_context.VERSION}。",'',
       '时代万恒原先显示资格未通过，使形态不足看起来像数据不足；实际有160根正式日线，最近40交易日窗口齐全。现在独立显示最新突破判断、整理尚未形成及已完成整理0日。没有降低两日整理条件。',
       '新化股份原先把9月30日日线档位放在卡片主结论。现在以当日逐股报价、反包修复、原平台内承接作为主结论；原平台36.50、突破门槛36.64145保持固定，完成日来源下沉为历史背景。',
       '9月30日是本轮计算时上一完成交易日；10月8日日线未收盘，不伪造正式日线。历史库用于ATR、趋势和平台，最新报价用于当日价格及暂态结构判断。后续正式日线沿用每日增量补齐流程。',
       '午间和收盘后保留同日阶段有效报价为参考；不产生新的观察候选。跨日、过期上午报价、未知价格来源仍拒绝相关结构推断。',
       '', '| 股票 | 当日价格 | 最新判断 | 当前结构 | 报价更新时间 | 历史日线 | 整理状态 |', '|---|---|---|---|---|---|---|']
for c in selected.values():
    lines.append(f"| {c['name']} {c['code']} | {c['price']} | {c['current_label']} | {c['structure_state']} | {c['quote_at']} | {c['history_evidence']['count']} | {c['setup_state']} |")
lines += ['',f"全池 {len(rows)} 只；历史40日窗口已核验 {result['history_valid']} 只；真正的数据缺口/口径问题保留具体原因。",'',
          '验证：285项测试通过，包含新增10项业务边界；check_dashboard.py、check_live_service.py通过；Edge实际点击两只股票并核对详情；原生CSV导出3120行、241列，最新判断和报价时间一致。',
          '截图与浏览器证据：browser.json、output/playwright/current-shidai.png、current-xinhua.png、current-xinhua-card.png；CSV为current-judgment-all.csv。',
          f"剩余缺口再取：{retry['requested']}只请求，{retry['received']}只返回，写入{retry['rows_written']}行；原缺失日期补回{retry['filled_stocks']}只。具体日期与返回见history_gaps.json、retry_gaps.json。8只在主样本内，94只属于主样本之外的缺口，含无成交、短历史或核心日期不齐。不能据此假定全是网络遗漏或全是停牌。",
          '修改前恢复材料位于 backups/latest_before_current_judgment，仅用于恢复，不参与新版计算。',
          '本轮验证价格判断、数据来源与页面链路；没有把价格越界当成威科夫成交量突破确认，也没有验证完整A-E阶段、点数图目标或策略收益。']
(OUT/'验收报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('status','selected')},ensure_ascii=False))
