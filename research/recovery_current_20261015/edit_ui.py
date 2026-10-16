from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def edit(name,changes):
    p=ROOT/name;s=p.read_text(encoding='utf-8')
    for old,new in changes:
        assert old in s,(name,old[:100]);s=s.replace(old,new)
    p.write_text(s,encoding='utf-8')
edit('stock_rank_ui.js',[
 ("不直接算作合格趋势。MA10有效失守则候选失效；出现正式强势入口后转为已确认。", "不直接算作合格趋势。仅展示最新一轮、含当前交易日在内最近5个交易日仍有效的候选；MA10失守、正式确认、过期及数据待核验时隐藏标签。"),
 ("function msRecoveryTag(m){var c=m.recovery_candidate;if(!c)return '';return msTag(c.active?'涨停收复':'涨停收复 · '+c.state,'候选事件 '+c.date+'；'+c.basis+'；事件量比 '+mtValue(c.volume_ratio)+'；历史启动 '+(c.previous_origin||'—')+'，旧波段退出 '+c.previous_exit+'；'+(c.reason||'以候选MA10继续观察，尚未确认强势入口')+(c.ended_at?'；结束 '+c.ended_at:''));}",
  "function msRecoveryCandidate(m){return m.recovery_current&&m.recovery_candidate&&m.recovery_candidate.active&&mtSnapshotFresh(m)?m.recovery_candidate:null;}\nfunction msRecoveryTag(m){var c=msRecoveryCandidate(m);if(!c)return '';return '<span class=\"ms-tag ms-recovery-tag\" '+msTipAttrs('涨停收复','本轮事件 '+c.date+'；第'+c.age_sessions+'/'+c.window_sessions+'个交易日；'+c.basis+'；事件量比 '+mtValue(c.volume_ratio)+'；最新核验 '+(m.quote_at||'—')+'；以候选MA10跟踪，尚未确认正式趋势')+'><span class=\"ms-recovery-dot\" aria-hidden=\"true\"></span><span>涨停收复</span><span class=\"ms-recovery-kind\">候选</span></span>';}") ,
 ("['涨停收复','涨停收复候选']", "['涨停收复','涨停收复（近5日）']"),
 ("return msMatchDirections(r)&&(!v.q", "return (v.phase!=='涨停收复'||!!msRecoveryCandidate(mt))&&msMatchDirections(r)&&(!v.q"),
 ("if(mt.stage)tags+=", "if(!mt.stage&&msRecoveryCandidate(mt))tags+=msTag('MA10跟踪',mt.reason,'ms-follow-tag');if(mt.stage)tags+="),
])
edit('ma_trend_ui.js',[
 ("if(phase==='涨停收复'&&!(m.recovery_candidate||{}).active)return false;", "if(phase==='涨停收复'&&!msRecoveryCandidate(m))return false;"),
 ("if(['trend','focus','advance'].indexOf(v.scope)>=0", "if(v.scope==='startup_pending'&&m.candidate_mode&&!msRecoveryCandidate(m))return false;\n  if(['trend','focus','advance'].indexOf(v.scope)>=0"),
 ("['涨停收复','涨停收复候选']", "['涨停收复','涨停收复（近5日）']"),
 ("function mtTable(rows,limit)", "function mtStatus(m){var badge=msRecoveryTag(m),status=m.status||'未入选';return '<div class=\"ma-status-stack\">'+(badge||'')+(badge&&status==='涨停收复·新启动候选'?'':'<span '+msTipAttrs(status,m.reason+(m.exit_at?'；确认退出时间 '+m.exit_at:''))+' class=\"ma-state '+(m.eligible?'ma-active':'ma-inactive')+'\">'+esc(status)+'</span>')+'</div>';}\nfunction mtOrigin(m){var c=msRecoveryCandidate(m),o=m.origin||{},p=m.platform||{};if(c)return '<div class=\"ma-current-event\"><b>本轮收复 '+esc(c.date)+'</b><span class=\"ma-event-age\">第 '+c.age_sessions+' / '+c.window_sessions+' 个交易日</span><span class=\"cd\">事件量比 '+mtValue(c.volume_ratio)+' · '+esc(c.state)+'</span></div>';return '<b '+msTipAttrs(o.kind||'无强势起点')+'>'+esc(o.kind||'无强势起点')+'</b><span class=\"cd\">'+(mtHistorical(m)||m.candidate_mode?'历史启动 ':'本轮启动 ')+esc(o.date||'—')+' · 最近确认 '+esc((m.last_confirmation||{}).date||o.date||'—')+'</span><span class=\"cd\">启动量比 '+mtValue(o.volume_ratio)+' · 上涨 '+pctHtml(o.day_return_pct)+'</span><span class=\"cd\">前段上涨 '+pctHtml(p.rise_pct)+' · 整理量比 '+mtValue(m.volume&&m.volume.consolidation_ratio)+'</span>';}\nfunction mtTable(rows,limit)"),
 ("<td><b '+msTipAttrs(m.status,m.reason+(m.exit_at?'；确认退出时间 '+m.exit_at:''))+' class=\"ma-state '+(m.eligible?'ma-active':'ma-inactive')+'\">'+esc(m.status||'未入选')+'</b>'+msRecoveryTag(m)", "<td>'+mtStatus(m)"),
 ("esc((mtHistorical(m)?'历史阶段 · ':'')+(m.stage_label||'暂无合格阶段'))", "esc(msRecoveryCandidate(m)?'待确认趋势 · MA10跟踪':(mtHistorical(m)?'历史阶段 · ':'')+(m.stage_label||'暂无合格阶段'))"),
 ("(m.stage||'—')+' '+mtValue(m.ma_value,3)", "(m.candidate_mode?10:m.stage||'—')+' '+mtValue(m.ma_value,3)"),
 ("<td class=\"l\">'+(m.recovery_candidate?'<b>涨停收复候选 '+esc(m.recovery_candidate.date)+'</b><span class=\"cd\">事件量比 '+mtValue(m.recovery_candidate.volume_ratio)+' · '+esc(m.recovery_candidate.state)+'</span>':'')+'<b '+msTipAttrs(o.kind||'无强势起点')+'>'+esc(o.kind||'无强势起点')+'</b><span class=\"cd\">'+(mtHistorical(m)||m.candidate_mode?'历史启动 ':'本轮启动 ')+esc(o.date||'—')+' · 最近确认 '+esc((m.last_confirmation||{}).date||o.date||'—')+'</span><span class=\"cd\">启动量比 '+mtValue(o.volume_ratio)+' · 上涨 '+pctHtml(o.day_return_pct)+'</span><span class=\"cd\">前段上涨 '+pctHtml(p.rise_pct)+' · 整理量比 '+mtValue(m.volume&&m.volume.consolidation_ratio)+'</span>", "<td class=\"l\">'+mtOrigin(m)+'"),
 ("function mtDetail(m){if(!m)return '';var p=", "function mtRecoveryDetail(m){var c=msRecoveryCandidate(m);if(!c)return '';return '<details class=\"card ma-trend-detail\"><summary>涨停收复判断依据 · 本轮候选</summary><div><p>'+msRecoveryTag(m)+'</p><p>本轮收复 '+esc(c.date)+' · 第 '+c.age_sessions+' / '+c.window_sessions+' 个交易日</p><p>'+esc(c.basis)+'；事件量比 '+mtValue(c.volume_ratio)+'，独立展示。</p><p>候选MA10触线价 '+mtValue(m.support_price,4)+' · 暂态MA10 '+mtValue(m.ma_value,4)+'</p><p>'+esc(m.mode)+' · 最新核验 '+esc(m.quote_at)+' · 完成日截至 '+esc(m.asof)+'</p><p class=\"ms-muted\">仅保留最近5个交易日内最新一轮有效候选；MA10有效失守、正式强势入口确认或窗口到期后隐藏候选标签。</p><p>'+esc(m.reason)+'</p></div></details>';}\nfunction mtDetail(m){if(!m)return '';if(msRecoveryCandidate(m))return mtRecoveryDetail(m);var p="),
 ("(m.recovery_candidate?'<p>'+msRecoveryTag(m)+' 候选日期 '+esc(m.recovery_candidate.date)+' · '+esc(m.recovery_candidate.state)+' · 事件量比 '+mtValue(m.recovery_candidate.volume_ratio)+'</p>':'')", "(msRecoveryCandidate(m)?'<p>'+msRecoveryTag(m)+'</p>':'')"),
 ("msTag(msMAStageLabel(row.ma_trend),row.ma_trend.reason)+msRecoveryTag(row.ma_trend)+' '+msTag(mtSnapshotFresh(row.ma_trend)?row.ma_trend.status:'快照已过期',row.ma_trend.reason)", "(msRecoveryCandidate(row.ma_trend)?msRecoveryTag(row.ma_trend):msTag(msMAStageLabel(row.ma_trend),row.ma_trend.reason)+' '+msTag(mtSnapshotFresh(row.ma_trend)?row.ma_trend.status:'快照已过期',row.ma_trend.reason))"),
])
edit('csv_export.js',[
 ("contexts=contexts||{};", "contexts=contexts||{};\n  function candidate(m){return m.recovery_current&&m.recovery_candidate&&m.recovery_candidate.active?m.recovery_candidate:{};}\n  function model(m){if(candidate(m).date)return m;var v=Object.assign({},m);delete v.recovery_candidate;return v;}"),
 ("(mt.recovery_candidate||{}).date,(mt.recovery_candidate||{}).state", "candidate(mt).date,candidate(mt).state"),
 ("(m.recovery_candidate||{}).date,(m.recovery_candidate||{}).state", "candidate(m).date,candidate(m).state"),
 ("JSON.stringify(mt)", "JSON.stringify(model(mt))"),
 ("JSON.stringify(m)", "JSON.stringify(model(m))"),
])
