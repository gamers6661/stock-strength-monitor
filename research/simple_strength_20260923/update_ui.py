"""本次界面迁移脚本；不参与服务运行。"""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
p = root / 'dashboard_template.html'
s = p.read_text(encoding='utf-8')

def replace_section(start, end, body):
    global s
    a, b = s.index(start), s.index(end, s.index(start))
    s = s[:a] + body + '\n' + s[b:]

s = s.replace('title="切换选股因子策略（两套因子完全独立）"', 'title="完成日线强势观察"')
s = s.replace('<button data-s="trend" class="on">波段趋势</button>', '<button data-s="trend" class="on">强势观察</button>')
s = s.replace('      <button data-s="ignition">短线启动</button>\n', '')
replace_section('        <div class="seg" id="seg-period">', '        <button class="btn" id="btn-filter">',
                '        <div class="seg" id="seg-period" style="display:none"><button data-k="all" class="on">20日排名</button></div>')
s = s.replace('次新由「上市 ≥120 交易日」门槛挡出，不参与打分', '个股至少具备61根对齐的完整日线，成交额使用估算口径')
s = s.replace('<h3>周期共振 <small>短线 / 波段 / 趋势 三项均 ≥ 70</small></h3>',
              '<h3>强势且有行业支持 <small>20日居前、站上60日线、行业同伴多数站上20日线</small></h3>')
s = s.replace("function strat(){ return STATE.strategy||(DATA.default_strategy||'trend'); }", "function strat(){ return 'trend'; }")
s = s.replace("if(k!=='trend'&&k!=='ignition')k='trend';", "k='trend';")
replace_section('  /* — 强势股表 — */', '  /* — 告警 — */', r'''
  /* — 完成日线强势观察 — */
  var tops=stocks.filter(function(s){return s.watch_candidate;});
  var h='<thead><tr><th class="l">名称</th><th>现价</th><th>今日</th><th>20日涨幅</th><th>行业广度</th><th class="l">观察状态</th></tr></thead><tbody>';
  tops.slice(0,10).forEach(function(s,i){
    h+='<tr class="clickable" onclick="showStock(\''+s.code+'\')">'
      +'<td class="l"><span class="rk">'+(i+1)+'</span> '+esc(s.name)+'<span class="cd">'+s.code+'</span></td>'
      +'<td>'+fmt(s.price)+'</td><td class="'+cls(s.change_pct)+'">'+pct(s.change_pct)+'</td>'
      +'<td class="'+cls(s.ret20)+'">'+pct(s.ret20,1)+'</td>'
      +'<td>'+(s.industry_breadth==null?'信息不足':fmt(s.industry_breadth,1)+'%')+'</td>'
      +'<td class="l">'+esc(s.entry_state)+(s.overheated?' · <span class="down">位置偏热</span>':'')+'</td></tr>';
  });
  document.getElementById('ov-stocks').innerHTML=h+'</tbody>';
  document.getElementById('ov-stk-sub').textContent='完成日线 '+((DATA.strength_model||{}).asof||'—')+' · 观察池 TOP 10';
''')
s = s.replace('n(s.score_short)>=70&&n(s.score_mid)>=70&&n(s.score_trend)>=70', 's.watch_candidate&&s.industry_supported')
s = s.replace('周期共振', '行业支持')
replace_section('  if(rsub){', '  host.innerHTML=ts.map', r'''
  if(rsub){
    rsub.innerHTML='按完成日线20日涨幅百分位分档，不代表买点或胜率。行业广度是同伴站上20日线的实际比例，不参与排名。<br>'
      +ts.map(function(t){return esc(t.label)+' '+rangeOf(t.key)+'　'+esc(t.desc);}).join('　｜　')
      +'。判断日：'+esc((DATA.strength_model||{}).asof||'—');
  }
''')
s=s.replace('高位/派发类风险项','位置或结构风险项').replace('高位/派发','位置/结构')
s=s.replace("+'<th>总分</th>'+F.map", "+'<th>20日分位</th>'+F.map")
s=s.replace('按总分列出前','按20日分位列出前').replace('按分数区间筛','按分位区间筛')
replace_section('/* 波段趋势 V3：五个交易因子', 'function activeFilterCount(){', r'''
var FACTORS=[['rs','20日分位'],['sector','行业广度%']];
var FACTORS_AUX=[['fund','主力资金分位（仅辅助）']];
var STATEFN={
  'watch':function(s){return s.watch_candidate;},
  'breakout':function(s){return s.entry_state==='突破观察';},
  'pullback':function(s){return s.pullback_observe;},
  'reso':function(s){return s.watch_candidate&&s.industry_supported;},
  'above60':function(s){return s.above60;},
  'above20':function(s){return s.above20;},
  'hot':function(s){return s.overheated;},
  'limit1':function(s){return n(s.limit_today)&&n(s.limit_streak)<=1;},
  'streak':function(s){return n(s.limit_streak)>=2;}
};
var STATE_LABEL={watch:'强势观察池',breakout:'突破观察',pullback:'回调观察',reso:'行业支持',above60:'站上60日线',above20:'站上20日线',hot:'位置偏热',limit1:'今日首板',streak:'连板'};
var STATE_TIP={watch:'20日分位至少80、20日涨幅为正且站上60日线',breakout:'完成日线收盘突破此前20日最高价，且在60日线上',pullback:'60日线上，收盘回落至20日线及以下；不要求缩量',reso:'强势观察池中，其他行业同伴至少半数站上20日线',above60:'完成日线收盘高于60日均线',above20:'完成日线收盘高于20日均线',hot:'现价距离20日均线超过3.5 ATR',limit1:'今日涨停且为第1板',streak:'连续2板及以上'};
var PRESETS={'全部有效样本':{},'强势观察池':{states:['watch']},'突破观察':{states:['watch','breakout']},'回调观察':{states:['watch','pullback']},'行业支持':{states:['reso']},'站上60日线':{states:['above60']},'位置偏热':{states:['hot']}};
''')
replace_section('function renderStocks(){', 'function renderFbar(){', r'''
function renderStocks(){
  document.getElementById('btn-filter').onclick=renderFilterPanel;
  document.getElementById('btn-cols').onclick=renderColPanel;
  var res=(DATA.stocks||[]).filter(passFilter);
  res=sortRows(res,STATE.sort.stocks.k||'score',STATE.sort.stocks.asc);
  var shown=res.slice(0,STATE.limit), C=STATE.cols, count=activeFilterCount();
  var badge=document.getElementById('fcount'); badge.style.display=count?'inline-block':'none';badge.textContent=count;
  document.getElementById('stk-res').innerHTML='命中 <b>'+res.length+'</b> 只 · 显示 '+shown.length;
  var h='<thead><tr>'+thSort('stocks','rank','#')+thSort('stocks','name','名称','l')
    +thSort('stocks','price','现价')+thSort('stocks','change_pct','今日涨跌')
    +thSort('stocks','ret20','20日涨幅')+thSort('stocks','score','20日分位')
    +thSort('stocks','ret60','60日涨幅')+thSort('stocks','above60','60日结构')
    +(C.industry?'<th class="l">行业</th>':'')+thSort('stocks','industry_breadth','行业广度%')
    +'<th class="l">入场标记</th><th class="l">风险 / 缺失</th>'
    +(C.extra?'<th>完成日量比</th><th>距20日线ATR</th>':'')
    +(C.board?'<th class="l">题材</th>':'')+'</tr></thead><tbody>';
  shown.forEach(function(s,i){
    h+='<tr class="clickable" onclick="showStock(\''+s.code+'\')">'
      +'<td>'+(i+1)+'</td><td class="l"><span class="nm">'+esc(s.name)+'</span><span class="cd">'+s.code+'</span>'+bpill(s)+'</td>'
      +'<td>'+fmt(s.price)+'</td><td class="'+cls(s.change_pct)+'">'+pct(s.change_pct)+'</td>'
      +'<td class="'+cls(s.ret20)+'">'+pct(s.ret20,1)+'</td><td>'+fmt(s.score,1)+'</td>'
      +'<td class="'+cls(s.ret60)+'">'+pct(s.ret60,1)+'</td><td>'+(s.above60?'<span class="up">线上</span>':'<span class="flat">线下</span>')+'</td>'
      +(C.industry?'<td class="l">'+esc(s.primary_industry||'未知')+'</td>':'')
      +'<td>'+(s.industry_breadth==null?'—':fmt(s.industry_breadth,1)+'<small class="flat"> / '+s.industry_peers+'同伴</small>')+'</td>'
      +'<td class="l">'+esc(s.entry_state)+'</td><td class="l" style="max-width:260px;white-space:normal">'+esc((s.risk_notes||[]).join('；')||'未触发既定阈值')+'</td>'
      +(C.extra?'<td>'+fmt(s.volume_ratio_closed)+'</td><td>'+fmt(s.live_dist_atr)+'</td>':'')
      +(C.board?'<td class="l"><div class="tags">'+displayBoards(s).slice(0,3).map(function(b){return tagHtml(b,(DATA.theme_index||{})[b]);}).join('')+'</div></td>':'')+'</tr>';
  });
  document.getElementById('tb-stocks').innerHTML=h+'</tbody>';
  document.getElementById('zero-tip').innerHTML=res.length?'':zeroTipHtml();
  document.getElementById('stk-more').innerHTML=res.length>shown.length?'<button class="btn" onclick="STATE.limit+=120;renderStocks()">加载更多</button>':'';
  var m=DATA.strength_model||{};
  document.getElementById('stk-sub').innerHTML='判断日 <b>'+esc(m.asof||'—')+'</b> · 20日涨幅排名，60日均线判断结构；行业广度、入场标记与风险独立展示。<br>'
    +'20日分位不是综合分或胜率；盘中报价另行更新。行业广度排除自身，至少需要'+n(m.min_industry_peers||5)+'个有效同伴；未知不补分。';
  renderFbar();
}
''')
replace_section('function exportCSV(){', '/* ── 个股详情 ── */', r'''
function exportCSV(){
  var res=sortRows((DATA.stocks||[]).filter(passFilter),STATE.sort.stocks.k||'score',STATE.sort.stocks.asc);
  var head=['代码','名称','报价快照时间','判断日','现价','今日涨跌%','20日涨幅%','20日分位','60日涨幅%','60日结构','行业','行业广度%','有效同伴','入场标记','风险'];
  function cell(x){return '"'+String(x==null?'':x).replace(/"/g,'""')+'"';}
  var lines=[head.map(cell).join(',')];
  res.forEach(function(s){lines.push([s.code,s.name,DATA.generated_at,s.signal_date,s.price,s.change_pct,s.ret20,s.score,s.ret60,s.above60?'线上':'线下',s.primary_industry,s.industry_breadth,s.industry_peers,s.entry_state,(s.risk_notes||[]).join('；')].map(cell).join(','));});
  var blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download='强势观察_'+((DATA.strength_model||{}).asof||'')+'.csv';a.click();toast('已导出 '+res.length+' 条');
}
''')
replace_section('function showStock(code){', 'function setThemeFilter(name){', r'''
function showStock(code){
  var s=(DATA.stocks||[]).filter(function(x){return x.code===code;})[0];if(!s)return toast('未找到 '+code);
  var h='<div class="grid g2">'
    +'<div class="metric"><div class="lbl">现价 / 今日涨跌</div><div class="val">'+fmt(s.price)+' <span class="'+cls(s.change_pct)+'">'+pct(s.change_pct)+'</span></div><div class="sub">报价快照 '+esc(DATA.generated_at)+'</div></div>'
    +'<div class="metric"><div class="lbl">20日涨幅 / 百分位</div><div class="val">'+pct(s.ret20,1)+' / '+fmt(s.score,1)+'</div><div class="sub">完成日线 '+esc(s.signal_date)+'；非综合分、非胜率</div></div></div>';
  h+='<div class="card" style="margin-top:16px"><h3>观察依据</h3><p>60日结构：<b>'+(s.above60?'站在线上':'未站上线')+'</b> · 完成日收盘 '+fmt(s.signal_close)+' / 60日均线 '+fmt(s.ma60)+'</p>'
    +'<p>行业：'+esc(s.primary_industry||'未知')+' · '+(s.industry_breadth==null?'有效同伴不足或归属未知，广度不补值':s.industry_peers+'个其他有效同伴中，'+s.industry_above20+'个站上20日线（'+fmt(s.industry_breadth,1)+'%）')+'</p>'
    +'<p>入场标记：<b>'+esc(s.entry_state)+'</b> · 前20日最高价 '+fmt(s.ph20)+' / 20日均线 '+fmt(s.ma20)+'</p>'
    +'<p>风险与缺失：'+esc((s.risk_notes||[]).join('；')||'未触发既定阈值')+'</p>'
    +'<p class="flat">行业广度不参与排名；突破须完成日线确认；回调不要求缩量。观察标记不代表买入指令。</p></div>';
  h+='<div class="card" style="margin-top:16px"><h3>近60日完成日线</h3>'+(s.k?'<canvas class="chart" id="k-cv" style="height:180px"></canvas>':'<p class="flat">当前未内联走势</p>')+'</div>';
  h+='<div class="grid g2" style="margin-top:16px">'+[['5日涨幅',pct(s.ret5,1)],['60日涨幅',pct(s.ret60,1)],['完成日成交量比',fmt(s.volume_ratio_closed)],['现价距20日线',fmt(s.live_dist_atr)+' ATR'],['估算20日成交额中位数',yi(s.amt_med20_wan)],['判断日',s.signal_date]].map(function(x){return '<div class="metric"><div class="lbl">'+x[0]+'</div><div class="val" style="font-size:22px">'+x[1]+'</div></div>';}).join('')+'</div>';
  h+='<div class="card" style="margin-top:16px"><h3>同花顺题材 · 仅供归属参考</h3><div class="tags">'+displayBoards(s).map(function(b){return tagHtml(b,(DATA.theme_index||{})[b]);}).join('')+'</div></div>';
  openDrawer(esc(s.name)+' '+esc(s.code),'20日涨幅排名 '+s.rank+' / '+DATA.stock_count,h);
  var paint=function(){var cv=document.getElementById('k-cv');if(cv&&s.k)drawTrend(cv,s.k);};paint();requestAnimationFrame(paint);
}

''')
replace_section('  function advice(r){', "  var h='<thead><tr>'", r'''
  function advice(r){
    var s=r.st;
    if(!s.above60)return ['结构偏弱','wa','完成日收盘未站上60日线'];
    if(s.overheated)return ['位置偏热','wa','现价距20日线超过3.5 ATR'];
    return [s.entry_state,'gr',(s.risk_notes||[]).join('；')||'未触发既定风险阈值；排名不代表持有建议'];
  }
''')
s=s.replace("+'<th>短线</th><th>趋势</th><th class=\"l\">题材</th><th class=\"l\">建议</th>'", "+'<th>行业广度%</th><th>60日结构</th><th class=\"l\">题材</th><th class=\"l\">观察</th>'")
s=s.replace("+'<td class=\"flat\">'+fmt(s.score_short,0)+'</td>'", "+'<td class=\"flat\">'+fmt(s.industry_breadth,1)+'</td>'")
s=s.replace("+'<td class=\"flat\">'+fmt(s.score_trend,0)+'</td>'", "+'<td class=\"flat\">'+(s.above60?'线上':'线下')+'</td>'")
s=s.replace("[['factors','七因子分'],['board','题材标签'],['industry','行业'],['extra','扩展列（60日/量比实时/市值）']]", "[['board','题材标签'],['industry','行业'],['extra','扩展列（完成日量比 / 距20日线）']]")
s=s.replace("'综合 '+f.scoreMin", "'20日分位 '+f.scoreMin")
s=s.replace("'综合强度'", "'20日分位'").replace('个股综合分', '个股20日分位').replace('现有综合强度', '20日涨幅排名')
s=s.replace('仅复用已有综合分','个股按20日涨幅排名')
s=s.replace("['加权强度',", "['加权分位',")
s=s.replace("var strong=found.filter(function(r){return n(r.st.score)>=70;}).length;", "var strong=found.filter(function(r){return r.st.above60;}).length;")
s=s.replace("var weak=found.filter(function(r){return n(r.st.score)<45;}).length;", "var weak=found.filter(function(r){return !r.st.above60;}).length;")
s=s.replace("['结构',strong+' 强 / '+weak+' 弱',(weak>strong?'注意弱势持仓占比':'结构健康')]", "['60日结构',strong+' 线上 / '+weak+' 线下','以完成日线判断']")
p.write_text(s,encoding='utf-8')
