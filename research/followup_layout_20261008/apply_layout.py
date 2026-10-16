from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'dashboard_template.html';t=p.read_text(encoding='utf-8')
start=t.index('          <details class="trend-reclaim" id="work-trend-comparison">')
end=t.index('          </details></details></div>',start)+len('          </details></details>')
t=t[:start]+t[end:]
t=t.replace('<details class="trend-reclaim"><summary id="work-consolidation-pending-title">','<details class="trend-reclaim ui-followup" id="work-followup-section"><summary id="work-consolidation-pending-title">',1)
t=t.replace('var WORK_MODE=null,WORK_MANUAL=false,TREND_LINE=5;','var WORK_MODE=null,WORK_MANUAL=false;',1)
start=t.index('function setTrendLine(period){');end=t.index('function autoWorkMode(){',start)
t=t[:start]+t[end:]
t=t.replace("var cb=DATA.close_strong_board||{},trend=DATA['trend_ma'+TREND_LINE+'_observation']||{};","var cb=DATA.close_strong_board||{};",1)
t=t.replace("var close=DATA.close_strong_board||{},trend=DATA['trend_ma'+TREND_LINE+'_observation']||{},fresh=DATA.intraday_new_strength||{};","var close=DATA.close_strong_board||{};",1)
start=t.index('  var workPhase=sessionNow(),lunchRetained=',t.index('function renderWorkboard(){'))
end=t.index("  document.getElementById('work-close-count')",start)
t=t[:start]+t[end:]
start=t.index("  document.getElementById('work-consolidation-pending').innerHTML=")
end=t.index('\n',start)
t=t[:start]+"  document.getElementById('work-consolidation-pending').innerHTML=completed.concat(pending,withdrawn).map(function(r){return uiFollowupCard(r,lookup,phase);}).join('')||'<div class=\"work-observation-empty\">当前无已完成整理、待核验或转弱退出记录</div>';"+t[end:]
# 标签在个股榜关键状态与详情的当前判断中显示，不参与排序、筛选或CSV。
old="+'<td class=\"l\"><span class=\"stock-key '+(key.risk?'risk-严重':'')+'\">'+esc(key.label)+'</span></td>'"
assert t.count(old)==1
t=t.replace(old,"+'<td class=\"l\"><span class=\"stock-key '+(key.risk?'risk-严重':'')+'\">'+esc(key.label)+'</span><div class=\"ui-pullback-tags\">'+uiTrendPullbackTags(s)+'</div></td>'",1)
old="    +'<details class=\"ui-evidence\"><summary>数据来源与历史背景</summary><div class=\"ui-evidence-body\">'"
assert t.count(old)==1
t=t.replace(old,"    +(uiTrendPullbackItems(s).length?'<div class=\"ui-pullback-row\" id=\"stock-trend-pullbacks\"><span class=\"ui-metric-label\">趋势线回踩</span><div class=\"ui-tags\">'+uiTrendPullbackTags(s)+'</div></div>':'')\n"+old,1)
assert 'work-trend-comparison' not in t and 'TREND_LINE' not in t
p.write_text(t,encoding='utf-8')
print('转强跟踪卡片与个股回踩标签已更新；首页旧均线区块及渲染代码已移除。')
