from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def edit(name,changes):
    p=ROOT/name;s=p.read_text(encoding='utf-8')
    if name=='stock_rank_ui.js' and 'function msRecoveryTag' in s:return
    for old,new in changes:
        if old==new:continue
        assert old in s,(name,old)
        s=s.replace(old,new)
    p.write_text(s,encoding='utf-8')
edit('stock_rank_ui.js',[
 ("var MS_EXPLANATIONS={", "var MS_EXPLANATIONS={\n '涨停收复':'旧波段已经结束，完成日收盘封住涨停，重新站上MA5及MA10且两线向上，前一日曾低于至少一条线。独立的新启动候选事件，不要求突破前20日高点，量比单独展示，不直接算作合格趋势。MA10有效失守则候选失效；出现正式强势入口后转为已确认。',\n '涨停收复·新启动候选':'完成日涨停收复已成立，继续跟踪候选MA10；尚未通过现有强势入口，不计入三阶段有效观察。候选日期与历史波段起点分别记录。',\n '候选已失效':'涨停收复候选的MA10有效失守；保留事件日期和失效依据供回看。',\n '阶段待确认':'已出现独立候选事件，但尚未通过MA5/MA10/MA20正式阶段准入。',"),
 ("function msMAStageLabel(m){", "function msRecoveryTag(m){var c=m.recovery_candidate;if(!c)return '';return msTag(c.active?'涨停收复':'涨停收复 · '+c.state,'候选事件 '+c.date+'；'+c.basis+'；事件量比 '+mtValue(c.volume_ratio)+'；历史启动 '+(c.previous_origin||'—')+'，旧波段退出 '+c.previous_exit+'；'+(c.reason||'以候选MA10继续观察，尚未确认强势入口')+(c.ended_at?'；结束 '+c.ended_at:''));}\nfunction msMAStageLabel(m){"),
 ("['MA20横盘再启动','MA20横盘再启动'],['趋势前排'", "['MA20横盘再启动','MA20横盘再启动'],['涨停收复','涨停收复候选'],['趋势前排'"),
 ("if(mt.pending)tags+=", "tags+=msRecoveryTag(mt);if(mt.pending)tags+="),
])
edit('ma_trend_ui.js',[
 ("['startup_pending','启动待确认']", "['startup_pending','启动待确认 / 新启动候选']"),
 ("['快速收回','快速收回']", "['快速收回','快速收回'],['涨停收复','涨停收复候选']"),
 ("+' class=\"ma-state ", "+' class=\"ma-state "),
 ("esc(m.status||'未入选')+'</b><span '", "esc(m.status||'未入选')+'</b>'+msRecoveryTag(m)+'<span '"),
 ("(mtHistorical(m)?'历史启动 ':'本轮启动 ')", "(mtHistorical(m)||m.candidate_mode?'历史启动 ':'本轮启动 ')"),
 ("<td class=\"l\"><b '+msTipAttrs(o.kind", "<td class=\"l\">'+(m.recovery_candidate?'<b>涨停收复候选 '+esc(m.recovery_candidate.date)+'</b><span class=\"cd\">事件量比 '+mtValue(m.recovery_candidate.volume_ratio)+' · '+esc(m.recovery_candidate.state)+'</span>':'')+'<b '+msTipAttrs(o.kind"),
 ("(m.data_reasons||[]).join('；'))+'</span></td>", "(m.data_reasons||[]).join('；'))+'</span>'+(m.minute_coverage?'<span class=\"cd\">分钟覆盖 '+esc(String(m.minute_coverage.first_at||'').slice(11))+'—'+esc(String(m.minute_coverage.last_at||'').slice(11))+' · '+m.minute_coverage.bars+'条</span>':'')+'</td>"),
 ("未入选 / 历史退出 / 待核验 · ", "新启动候选 / 未入选 / 历史退出 / 待核验 · "),
 ("退出记录仅供回看，不代表当前阶段。", "涨停收复以候选事件标签显示，尚未计入三阶段有效观察。退出记录仅供回看，不代表当前阶段。"),
 ("(mtHistorical(m)?'历史波段起点 ':'本轮强势启动 ')", "(mtHistorical(m)||m.candidate_mode?'历史波段起点 ':'本轮强势启动 ')"),
 ("'<p>最近强势确认 '", "'<p>最近强势确认 '"),
 ("<p>阶段转换 ", "'+(m.recovery_candidate?'<p>'+msRecoveryTag(m)+' 候选日期 '+esc(m.recovery_candidate.date)+' · '+esc(m.recovery_candidate.state)+' · 事件量比 '+mtValue(m.recovery_candidate.volume_ratio)+'</p>':'')+'<p>阶段转换 "),
 ("<p>锁定平台 ", "<p>'+esc(pl.confirmed?'锁定平台':'承接区间（平台尚未确认）')+' "),
 ("<p class=\"ms-muted\">'+esc((m.data_reasons", "'+(m.minute_coverage?'<p>分钟来源 '+esc(m.minute_coverage.source)+' · 覆盖 '+esc(m.minute_coverage.first_at)+' 至 '+esc(m.minute_coverage.last_at)+' · '+m.minute_coverage.bars+' 条；对应报价 '+esc(m.minute_coverage.quote_at)+'</p>':'')+'<p class=\"ms-muted\">'+esc((m.data_reasons"),
 ("msTag(msMAStageLabel(row.ma_trend),row.ma_trend.reason)", "msTag(msMAStageLabel(row.ma_trend),row.ma_trend.reason)+msRecoveryTag(row.ma_trend)"),
])
edit('csv_export.js',[
 ("'完整排名依据','完整均线依据'", "'涨停收复候选日期','涨停收复候选状态','完整排名依据','完整均线依据'"),
 ("DATA.stock_board_ranking.version,JSON.stringify(item)", "DATA.stock_board_ranking.version,(mt.recovery_candidate||{}).date,(mt.recovery_candidate||{}).state,JSON.stringify(item)"),
 ("'有效截至','完整均线依据'", "'有效截至','涨停收复候选日期','涨停收复候选状态','完整均线依据'"),
 ("m.valid_until,JSON.stringify(m)", "m.valid_until,(m.recovery_candidate||{}).date,(m.recovery_candidate||{}).state,JSON.stringify(m)"),
])
