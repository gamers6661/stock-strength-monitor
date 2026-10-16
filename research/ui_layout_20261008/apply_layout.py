"""只重排模板的展示片段，保留候选计算、顺序和数据对象。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'dashboard_template.html';text=p.read_text(encoding='utf-8')

def section(start,end,replacement):
    global text
    assert text.count(start)==1,start
    a=text.index(start);b=text.index(end,a)
    text=text[:a]+replacement+text[b:]

section("    return '<button type=\"button\" class=\"work-observation\" onclick=\"showStock(\\''+jsq(s.code)",
        "  }).join('')||'<div class=\"work-observation-empty\">'+(normal?",r'''    var source=lookup[String(s.code)]||s,c=source.session_context||{},currentContext=contextCurrent(c)&&c.price_basis_valid;
    var label=currentContext?(c.current_label||c.label):s.live_attack_stage;
    var priceHtml='<span class="work-observation-change '+(shown?cls(shown.change):'flat')+'">'+(shown?'¥'+fmt(shown.price,2)+'　'+pct(shown.change,1):'报价待核验')+'</span>';
    return uiCardStart(s,priceHtml,lookup)
      +'<div class="ui-tags">'+uiTag(label||'形态待核验','blue',(currentContext?(c.current_pattern||{}).note:s.live_attack_status)||'沿用本轮价格形态判断，待收盘确认。')
      +uiTag(usable?'暂态A':state,'',usable?'沿用现有本轮达标结果；盘中暂态，待收盘确认。':'沿用最近有效观察，不生成新的盘中资格。')
      +uiRisk(risk,s.intraday_risk_level==='待核验')+'</div>'
      +'<div class="ui-metrics">'+uiMetric('综合进攻',s.live_attack_score==null?null:fmt(s.live_attack_score,1),'分','已有价格与资金综合进攻分；判断截至 '+(s.intraday_judgment_at||s.intraday_quote_at||'未知')+'。',s.live_attack_score)
      +uiMetric('价格进攻',s.live_attack_price_score==null?null:fmt(s.live_attack_price_score,1),'分','已有价格进攻分，资金不改变价格档位。')
      +uiMetric('距盘中 MA5',s.live_overheat_dist_atr==null?null:fmt(s.live_overheat_dist_atr,2),'ATR','沿用现有距离；严格超过3.5 ATR才触发位置偏热。')+'</div>'
      +'<div class="ui-card-foot">'+uiFund(s.live_attack_fund)+'<span>'+esc(lunch?'上午参考':usable?'本轮报价':'最近参考')+' · '+uiTime(reference?(reference.sourceAt||reference.at):(s.intraday_quote_at||s.intraday_judgment_at))+'</span></div></article>';
''')

section("    return '<button type=\"button\" class=\"work-observation\" onclick=\"showStock(\\''+jsq(r.code)",
        "  }).join('');\n  document.getElementById('work-consolidation-list')",r'''    var c=(lookup[String(r.code)]||{}).session_context||{},valid=contextCurrent(c)&&c.price_basis_valid;
    var label=valid?(c.current_label||c.label):r.stage;
    return uiCardStart(r,consolidationPrice(r),lookup)
      +'<div class="ui-tags">'+uiTag(r.stage||'整理观察','blue',shown.label+'；'+shown.note+'。'+(r.structure_note||''))
      +uiTag(label||'形态待核验','',valid?(c.current_pattern||{}).note||c.reason:shown.note)
      +(valid?uiTag(uiStructure(c.structure_state),'',c.structure_state+'；原平台突破门槛 '+(c.breakout_threshold==null?'待核验':'¥'+fmt(c.breakout_threshold,4))+'。'):'')
      +uiSupport(r)+(risk?uiRisk(r.risk_flags||[],false):'')+'</div>'
      +'<div class="ui-metrics">'+uiMetric('完成整理',r.consolidation_elapsed_days==null?r.days:r.consolidation_elapsed_days,'日',consolidationPeriodText(r)+'；当日未完成部分不计入。')
      +uiMetric('整理量 / 上涨量',r.volume_ratio==null?null:fmt(r.volume_ratio,2),'×',volume+'；完成日历史量，不是盘中同时间量比。')
      +uiMetric('完成日回撤',r.pullback_atr==null?null:fmt(r.pullback_atr,2),'ATR','沿用现有完成日回撤结果。')+'</div>'
      +'<div class="ui-card-foot">'+uiTag(confirmation+' '+samples+' 次','',confirmation+'已有 '+samples+' 次有效采样；平台试探 '+(r.breakout_samples||0)+' 次、转强 '+(r.turn_samples||0)+' 次、守线 '+(r.hold_samples||0)+' 次。采样不能证明间隔期间始终守线。')
      +'<span>'+esc(lunch?'上午参考':shown.reference?'最近参考':'本轮报价')+' · '+uiTime(r.quote_at)+'</span></div></article>';
''')

section('function sessionContextDetail(s){','function strengthHistoryText(s,key){',r'''function sessionContextDetail(s){
  var c=s.session_context;if(!c)return '';
  var current=contextCurrent(c),valid=current&&c.price_basis_valid,e=c.history_evidence||{};
  var flags=(c.risks||[]).slice(),a=s.live_attack_score,f=s.live_attack_fund;
  var high=valid&&c.current_pattern?c.current_pattern.high20:null;
  var setup=uiStructure(c.setup_state==='尚未形成整理'?'尚无已确认整理平台':c.setup_state);
  var h='<div class="detail-panel ui-decision" id="session-context-detail"><div class="ui-panel-head"><div class="detail-panel-title">当前判断</div>'
    +'<span class="ui-panel-time">'+esc(current?(c.stage==='午间休市'?'午间参考':c.stage==='已收盘'?'收盘参考':'当日观察'):'最近参考')+' · '+uiTime(c.quote_at)+'</span></div>'
    +'<div class="ui-tags">'+uiTag(c.current_label||c.label,valid?'blue':'',valid?(c.current_pattern||{}).note||c.reason:'当前报价或价格口径需更新，保留已有结果。')
    +(c.structure_state?uiTag(uiStructure(c.structure_state),'',c.structure_state+'。'+(c.breakout_threshold==null?'':'原平台突破门槛 ¥'+fmt(c.breakout_threshold,4)+'；价格越界仍需成交量和收盘确认。')):'')
    +uiRisk(flags,!valid||s.intraday_risk_level==='待核验')
    +(!e.valid?uiTag('历史待核验','warn',e.reason||'历史窗口尚未完成核验'):'')+'</div>'
    +'<div class="ui-metrics">'+uiMetric('综合进攻',a==null?null:fmt(a,1),'分','原有综合进攻分；'+(s.live_attack_tier||'待核验')+'档；判断截至 '+(s.intraday_judgment_at||s.intraday_quote_at||'未知')+'。',a)
    +uiMetric('最新价格进攻',valid&&c.price_attack_score!=null?fmt(c.price_attack_score,1):null,'分','原有最新价格分；'+(c.price_attack_tier||'待核验')+'档；报价 '+(c.quote_at||'未知')+'。')
    +uiMetric('距盘中 MA5',s.live_overheat_dist_atr==null?null:fmt(s.live_overheat_dist_atr,2),'ATR','原有距离。严格超过3.5 ATR触发位置偏热；分数不抵消风险。')
    +uiMetric(valid&&c.breakout_threshold!=null?'原平台突破门槛':'20日高点',valid&&c.breakout_threshold!=null?fmt(c.breakout_threshold,2):high==null?null:fmt(high,2),'元','已换算到当前报价尺度。原平台固定；20日高点仅为价格形态参考。')+'</div>'
    +'<div class="ui-tags">'+uiFund(f)+uiTag(setup||'整理待核验','',c.setup_reason||'沿用原有整理资格。')
    +uiTag('判断依据','',c.atr_method+'。\n'+(c.reason||'')+'\n报价更新 '+(c.quote_at||'未知')+'；'+(c.observation_mode||c.stage)+'。\n完成日基准 '+(c.background_asof||c.previous_close_asof)+'；已有 '+(e.count||0)+' 根日线，'+(e.valid?'最近40日窗口已核验':e.reason||'窗口待核验')+'。')+'</div>'
    +'<details class="ui-evidence"><summary>数据来源与历史背景</summary><div class="ui-evidence-body">'
    +'最新报价 '+esc(c.quote_at||'未知')+'；'+esc(c.observation_mode||c.stage)+'；'+esc(c.reason||'')+'。<br>'
    +'历史基准 '+esc(c.background_asof||c.previous_close_asof)+'；'+esc(c.baseline_source)+'；日线 '+esc(c.prior_daily_tier||'待评分')+'档；'+(c.previous_close_board?'属于真实收盘主榜':'不在真实收盘主榜')+'。<br>'
    +esc(c.atr_method)+'；ATR20 '+(c.atr20==null?'待核验':fmt(c.atr20,4))+'；较昨收 '+(c.gap_atr==null?'待核验':sgn(c.gap_atr,2)+' ATR')+'。<br>'
    +'历史 '+(e.count||0)+' 根；'+esc(e.reason||'最近40日窗口已核验')+'。</div></details></div>';
  return h;
}
''')

# 只折叠原有详细依据；每一段原文仍保留。
section("  h+='<div class=\"detail-panel\" style=\"margin:12px 0 18px\"><div class=\"detail-panel-title\">盘中进攻与再启动</div>'",'  var path=s.intraday_path;',"  var pathMarkerForLayout=true;\n")
# 把新的判断面板放在走势和日线评分之前。
text=text.replace('  h+=sessionContextDetail(s);\n','',1)
start="  h+='<div class=\"detail-main-grid\">'"
assert text.count(start)==1
text=text.replace(start,'  h+=sessionContextDetail(s);\n'+start,1)

start="    h+='<div class=\"detail-panel\" style=\"margin-bottom:18px\"><div class=\"detail-panel-title\">整理历史与确认过程 · '"
assert text.count(start)==1
text=text.replace(start,"    h+='<div class=\"detail-panel ui-consolidation\"><div class=\"ui-panel-head\"><div class=\"detail-panel-title\">整理观察</div><span class=\"ui-panel-time\">'+uiTime(c.quote_at)+'</span></div><div class=\"ui-tags\">'+uiTag(c.stage||'条件未满足',c.eligible?'blue':'',c.reason||cd&&cd.note||'沿用原有整理条件')+uiSupport(c)+'</div>'+(c.eligible||c.completion_confirmed||c.phase==='completed'?uiConsolidationMetrics(c):'')+'</div>';\n    h+='<details class=\"ui-evidence\"><summary>整理依据与确认记录</summary><div class=\"detail-panel\"><div class=\"detail-panel-title\">整理历史与确认过程 · '",1)
start="    h+='<p class=\"flat\">整理质量仅用于本板块排序，不改变日线进攻分；盘中采样不能证明采样间始终守线。</p></div>';"
assert text.count(start)==1
text=text.replace(start,start.replace("</p></div>'","</p></div></details>'"),1)

# 固定平台历史和采样表默认收起。
text=text.replace("var h='<div class=\"detail-panel\" id=\"structure-detail\">", "var h='<details class=\"ui-evidence\"><summary>固定平台与量价依据</summary><div class=\"detail-panel\" id=\"structure-detail\">",1)
start=text.index('function structureDetail(code){');end=text.index('function renderConsolidationMonitor(lookup){',start)
piece=text[start:end];assert piece.count("return h+'</div>';")==1
text=text[:start]+piece.replace("return h+'</div>';","return h+'</div></details>';")+text[end:]
start="    h+='<div class=\"detail-panel\" style=\"margin-bottom:18px\"><div class=\"detail-panel-title\">日内采样路径 · '"
assert text.count(start)==1
text=text.replace(start,"    h+='<details class=\"ui-evidence\"><summary>日内采样路径<small>'+esc(path.state)+'</small></summary><div class=\"detail-panel\" style=\"margin-bottom:18px\"><div class=\"detail-panel-title\">日内采样路径 · '",1)
start="+esc(path.note)+'</p></div>';"
assert text.count(start)==1
text=text.replace(start,"+esc(path.note)+'</p></div></details>';",1)
# 对完整盘中核验大区保留原数据，统一折叠。
text=text.replace('  var basisPending=String(s.intraday_trend_state',"  h+='<details class=\"ui-evidence\"><summary>均线、盘中资格与完整核验</summary><div class=\"ui-evidence-body\">';\n  var basisPending=String(s.intraday_trend_state",1)
text=text.replace("  h+='<details class=\"detail-fold detail-insight\"><summary><span class=\"detail-insight-icon\">◉</span>'", "  h+='</div></details>';\n  h+='<details class=\"detail-fold detail-insight\"><summary><span class=\"detail-insight-icon\">◉</span>'",1)

text=text.replace("          <p class=\"work-sub\">价格进攻85%＋主力资金15%；超大单参考按7.5%，资金待核验则沿用价格分。反包与突破单列；距MA5超过3.5 ATR标记位置偏热。</p>","          <div class=\"ui-rule-strip\" id=\"ui-attack-rules\"></div>",1)
text=text.replace("document.getElementById('work-consolidation-note').textContent='首次入榜须整理前及当前多头排列，此前5日涨15%或10日涨20%，历史A档不豁免。回踩至少2日、横盘至少3日。原合格对象MA10失守降级，继续观察MA20承接；MA20连续两次有效报价失守或正式收盘失守才退出。收复需两次确认，当前进攻另行复核。支撑上方0.4 ATR内提示接近，位置提示不代表反弹确认。';", "document.getElementById('work-consolidation-note').innerHTML=uiTag('整理条件','', '此前5日涨15%或10日涨20%，整理前和当前多头排列；历史A档不豁免。回踩至少2日、横盘至少3日。')+uiTag('守线规则','', '原合格对象MA10失守降级；MA20连续两次有效报价失守或正式收盘失守退出。收复需两次确认。')+uiTag('支撑提示','', '支撑上方0.4 ATR内提示接近，只代表位置，不代表反弹确认。');",1)
text=text.replace('  segInit(document.getElementById(\'seg\'),', "  initUiNotes();\n  document.getElementById('ui-attack-rules').innerHTML=uiTag('价格为主','', '原计分：价格进攻85%＋主力资金15%；超大单参考权重7.5%。资金未核验沿用价格分；价格非A不靠资金升A。')+uiTag('风险独立','', '反包与突破单列；距盘中MA5严格超过3.5 ATR标记位置偏热，不抵消风险。')+uiTag('标签可查看注释','', '悬停、点击或键盘聚焦标签可查看依据；完整记录在个股详情中展开。');\n  segInit(document.getElementById('seg'),",1)
text=text.replace('<p class="work-sub" id="work-consolidation-note">','<div class="ui-rule-strip" id="work-consolidation-note">',1).replace('只观察尚在整理及初步启动；已明显转强移出主名单。</p>','只观察尚在整理及初步启动；已明显转强移出主名单。</div>',1)
# 删除本次替换用的临时标记变量。
text=text.replace('  var pathMarkerForLayout=true;\n','')
p.write_text(text,encoding='utf-8')
print('展示片段已重排；筛选计算和导出逻辑未修改。')
