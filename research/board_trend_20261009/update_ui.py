from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'dashboard_template.html'
text = path.read_text(encoding='utf-8')
start = text.index("var BC_KIND='industry',BC_SORT='trend',BC_SEARCH='';")
end = text.index('function renderBoards(){', start)
text = text[:start] + r'''var BC_KIND='industry',BC_SORT='trend',BC_SEARCH='',BC_FILTER='all';
var BC_FILTERS=[['all','全部'],['online','趋势在线'],['initial','初步转强'],['pullback','回踩观察'],['weakening','趋势走弱'],['diffusion','成员扩散']];
function boardCatalog(){return DATA.board_catalog||[];}
function boardById(id){return boardCatalog().filter(function(b){return b.id===id;})[0];}
function boardMatches(b,key){
  if(key==='all')return true;
  if(!b.ranking_eligible)return false;
  if(key==='diffusion')return !!b.member_diffusion;
  var t=b.index_trend||{};
  return !!t.ready&&!!t[{online:'trend_online',initial:'initial_strength',pullback:'pullback',weakening:'weakening'}[key]];
}
function boardTrendTags(b){
  var t=b.index_trend,h='';
  if(!t)h+=uiTag('成员趋势观察','','未找到与当前行业/题材精确同名的同花顺指数，只观察已覆盖的主板成员。');
  else if(!t.ready)h+=uiTag('指数待核验','warn',(t.reason||'历史尚未对齐')+'；目标 '+(t.expected_asof||b.asof)+'；最新可用 '+(t.asof||'无')+'。不进入指数趋势筛选。');
  else{
    h+=uiTag(t.state,t.weakening?'risk':t.trend_online?'good':'',
      '完成日线 '+t.asof+'；MA5 > MA10 > MA20，MA20较前日上升，收盘≥MA10，全部满足才为趋势在线。初步转强表示前一天未在线、当前在线；走弱表示相反。');
    if(t.pullback)h+=uiTag(t.pullback_kind,'blue','前日和当前趋势在线；当日触及MA10后收回，或收盘在MA10上方0.4ATR内。是回踩位置观察，尚未确认反弹。');
  }
  h+=uiTag('成员 · '+(b.trend_state||'待观察'),b.member_diffusion?'blue':'',
    '当前有效主板成员的近3个完成日线：在线成员连续两次增加且在线比例高于全体主板，才标记持续扩散。不是历史全市场成分回测，也不证明带动关系。');
  if(!b.ranking_eligible)h+=uiTag('小样本','warn',b.ranking_reason||'有效成员不足6只，不参与正式筛选及排名。');
  if(b.wide)h+=uiTag('宽题材','','成员超过60只，建议结合详情中的细分成员观察。');
  return h;
}
function boardCard(b){
  var t=b.index_trend||{},valid=n(b.valid_members),ready=t.ready;
  return '<article class="bc-card" data-board-id="'+esc(b.id)+'">'
    +'<div class="bc-card-head"><button type="button" class="bc-name" onclick="showBoardById(\''+jsq(b.id)+'\')">'+esc(b.name)+'</button>'
    +'<span class="bc-kind">'+(b.type==='industry'?'行业':'题材')+'</span></div>'
    +'<div class="ui-tags">'+boardTrendTags(b)+'</div>'
    +'<div class="ui-metrics">'+uiMetric('指数5日',ready?pct(t.ret5,1):'—','','同花顺指数（含非主板成员）的完成日线收益。')
    +uiMetric('距MA10',ready&&t.ma10_distance_atr!=null?sgn(t.ma10_distance_atr,2):'—','ATR','(指数收盘−MA10) / ATR20；ATR为20个含跳空TR的简单平均。')
    +uiMetric('成员在线',fmt(b.trend_pct,0),'%',valid+'只有效主板成员中的趋势在线占比；日变化 '+sgn(b.trend_delta1_pp,1)+'个百分点。',b.trend_pct)+'</div>'
    +'<div class="bc-card-foot"><span>'+valid+'只 · 覆盖 '+fmt(b.valid_coverage_pct,0)+'%</span>'
    +'<span class="'+cls(b.member_today)+'">成员今日 '+pct(b.member_today,1)+'</span></div></article>';
}
function setBoardFilter(key){BC_FILTER=key;renderBoards();renderThemesPage();}
function centerMarkup(kind,showTabs){
  var all=boardCatalog().filter(function(b){return b.type===kind&&b.valid_members>0;});
  if(BC_SEARCH)all=all.filter(function(b){return b.name.toLowerCase().indexOf(BC_SEARCH.toLowerCase())>=0;});
  var boards=all.filter(function(b){return boardMatches(b,BC_FILTER);});
  boards.sort(function(a,b){
    if(a.ranking_eligible!==b.ranking_eligible)return a.ranking_eligible?-1:1;
    if(!a.ranking_eligible)return a.name.localeCompare(b.name);
    if(BC_SORT==='today')return n(b.member_today)-n(a.member_today)||n(b.emotion_pct)-n(a.emotion_pct);
    return n(a.trend_rank,1e9)-n(b.trend_rank,1e9)||a.name.localeCompare(b.name);
  });
  return '<div class="card bc-toolbar"><div class="row wrap" style="gap:8px;align-items:center">'
    +(showTabs?'<button class="btn '+(kind==='industry'?'primary':'')+'" onclick="BC_KIND=\'industry\';renderBoards()">行业</button>'
      +'<button class="btn '+(kind==='theme'?'primary':'')+'" onclick="BC_KIND=\'theme\';renderBoards()">题材</button>':'')
    +'<button class="btn '+(BC_SORT==='trend'?'primary':'')+'" onclick="BC_SORT=\'trend\';renderBoards();renderThemesPage()">成员趋势排序</button>'
    +'<button class="btn '+(BC_SORT==='today'?'primary':'')+'" onclick="BC_SORT=\'today\';renderBoards();renderThemesPage()">今日热度</button>'
    +'<input id="bc-search-'+(showTabs?'boards':'themes')+'" aria-label="搜索板块" placeholder="搜索行业或题材" value="'+esc(BC_SEARCH)+'" '
    +'oninput="updateBoardSearch(this)" class="bc-search"></div>'
    +'<div class="bc-filters" role="group" aria-label="板块趋势筛选">'+BC_FILTERS.map(function(x){
      return '<button type="button" data-board-filter="'+x[0]+'" aria-pressed="'+(BC_FILTER===x[0])+'" class="bc-filter '+(BC_FILTER===x[0]?'active':'')+'" onclick="setBoardFilter(\''+x[0]+'\')">'
        +x[1]+'<span>'+all.filter(function(b){return boardMatches(b,x[0]);}).length+'</span></button>';}).join('')+'</div>'
    +'<div class="bc-reference"><span>完成日线 '+esc((DATA.board_trend_model||DATA.strength_model||{}).asof||'—')+'</span>'
    +uiTag('筛选口径','','指数筛选须22个连续交易日对齐且至少6只有效主板成员。成员扩散独立判断；今日行情和资金不提升指数日线资格。回踩仅观察位置，本轮不做威科夫整理突破确认。')
    +'<span>'+boards.length+' / '+all.length+' 个</span></div></div>'
    +'<div class="bc-grid">'+(boards.length?boards.map(boardCard).join(''):'<div class="empty bc-empty">当前没有符合条件的板块，可切换筛选或清空搜索。</div>')+'</div>';
}
''' + text[end:]
start = text.index("  var source=b.source_members==null?'未知':n(b.source_members);", text.index('function showBoardById(id)'))
end = text.index('  if(b.wide){', start)
text = text[:start] + r'''  var idx=b.index_trend||{},ready=!!idx.ready;
  var h='<section class="card ui-decision bc-detail"><div class="ui-panel-head"><h3>指数趋势</h3><span class="flat">完成日线 '+esc(b.asof)+'</span></div>'
    +'<div class="ui-tags">'+boardTrendTags(b)+'</div>'
    +'<div class="ui-metrics">'+uiMetric('指数5日',ready?pct(idx.ret5,1):'—','','完成日线收益；指数包括非主板成员。')
    +uiMetric('指数20日',ready?pct(idx.ret20,1):'—','','20个交易日的指数收盘收益。')
    +uiMetric('距MA10',ready&&idx.ma10_distance_atr!=null?sgn(idx.ma10_distance_atr,2):'—','ATR','(指数收盘−MA10) / ATR20。')
    +uiMetric('ATR20',ready?fmt(idx.atr20,2):'—','点','20个含跳空真实波幅TR的简单平均。')+'</div>'
    +(ready?'<div class="bc-line-values">收盘 '+fmt(idx.close,2)+'<span>MA5 '+fmt(idx.ma5,2)+'</span><span>MA10 '+fmt(idx.ma10,2)+'</span><span>MA20 '+fmt(idx.ma20,2)+'</span></div>':'')+'</section>'
    +'<section class="card ui-decision bc-detail"><h3>主板成员参与</h3><div class="ui-metrics">'
    +uiMetric('成员在线',fmt(b.trend_pct,1),'%',n(b.valid_members)+'只有效成员中的趋势在线比例。',b.trend_pct)
    +uiMetric('较前日',sgn(b.trend_delta1_pp,1),'点','当前有效成员的在线比例变化；成员范围按当前归属计算。')
    +uiMetric('较全体主板',sgn(b.trend_vs_market_pp,1),'点','板块成员在线比例减全体有效主板在线比例。')
    +uiMetric('有效成员',n(b.valid_members),'只','当前归集 '+n(b.pool_members)+'只，日线覆盖 '+fmt(b.valid_coverage_pct,1)+'%。')+'</div>'
    +'<div class="ui-tags">'+uiTag('今日等权 '+pct(b.member_today,1),'','当前已覆盖有效主板成员的等权涨跌幅；不参与指数日线筛选。')
    +uiTag('涨停 '+n(b.limit_count)+'只','','已覆盖有效主板成员的当日涨停家数。')
    +uiTag('前三贡献 '+(b.positive_top3_share==null?'—':fmt(b.positive_top3_share,0)+'%'),'','上涨前三只的正收益之和 / 全部成员正收益之和；高比例可能由少数成员贡献。')
    +uiTag('资金覆盖 '+n(b.fund_today_covered||b.fund_covered)+'/'+n(b.valid_members),'','真实资金覆盖；未知不计中性分，不参与指数趋势资格。')+'</div></section>'
    +'<details class="detail-fold"><summary>数据与判断依据</summary><div class="detail-fold-body">'
    +'<p>指数来源：'+esc(idx.source||'未找到精确同名指数；只展示主板成员观察')+'。最新可用 '+esc(idx.asof||'—')+'，判断基准 '+esc(b.asof)+'。'
    +(ready?'22个连续交易日已对齐。':esc(idx.reason||'无对应指数。'))+'</p>'
    +'<p>趋势在线：MA5&gt;MA10&gt;MA20，MA20较前日上升，收盘≥MA10；前日用同样条件。ATR20是20个含跳空TR的简单平均。回踩观察不等于反弹确认。</p>'
    +'<p>成员来源：'+esc(b.source_basis)+'；'+esc(b.ranking_reason)+'。当前成员的近3日变化仅作扩散观察，不能代表历史全市场成员。'
    +(b.membership_disagreements!=null?' F10/详情归属差异 '+n(b.membership_disagreements)+'只。':'')+'</p>'
    +'<p>资金采集 '+esc(b.fund_observed_at||'未知')+'；来源 '+esc(DATA.fund_source||'未知')+'。'
    +(b.fund_today_covered?'已覆盖成员当日净额合计 '+sgn(b.fund_sum_today/1e8,2)+'亿元。':'')+'</p></div></details>';
''' + text[end:]
css = '''
.bc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:20px}
.bc-card{background:var(--card,#fff);border:1px solid var(--line);border-radius:14px;padding:18px;min-width:0;transition:border-color .15s,box-shadow .15s}
.bc-card:hover{border-color:#b7cce9;box-shadow:0 4px 16px #1b3f6b09}
.bc-card-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.bc-name{font:inherit;font-size:16px;font-weight:650;border:0;padding:0;background:none;color:var(--txt);cursor:pointer;text-align:left}
.bc-name:hover{color:var(--blue)}.bc-name:focus-visible{outline:2px solid var(--blue);outline-offset:4px}
.bc-kind,.bc-card-foot{font-size:11px;color:var(--txt3)}
.bc-card .ui-tags{min-height:50px;align-content:flex-start;margin-top:12px}.bc-card .ui-metric-value{font-size:21px}
.bc-card-foot{display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--line);padding-top:11px;margin-top:14px}
.bc-toolbar{margin-bottom:15px}.bc-search{margin-left:auto;max-width:240px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;background:var(--card,#fff);color:var(--txt)}
.bc-filters{display:flex;flex-wrap:wrap;gap:7px;margin:18px 0 12px}
.bc-filter{font:inherit;font-size:12px;color:var(--txt2);background:#f4f6f8;border:1px solid transparent;border-radius:9px;padding:8px 11px;cursor:pointer}
.bc-filter span{margin-left:8px;font-variant-numeric:tabular-nums;color:var(--txt3)}
.bc-filter.active{background:#edf4ff;color:#245cad;border-color:#d2e1f7}.bc-filter.active span{color:#245cad}
.bc-reference{display:flex;align-items:center;gap:12px;color:var(--txt3);font-size:11px}.bc-reference>span:last-child{margin-left:auto}
.bc-empty{grid-column:1/-1}.bc-detail{margin-bottom:16px}.bc-line-values{display:flex;flex-wrap:wrap;gap:16px;padding-top:12px;border-top:1px solid var(--line);color:var(--txt2);font-size:12px}
@media(max-width:1150px){.bc-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.bc-grid{grid-template-columns:minmax(0,1fr)}.bc-search{margin-left:0;width:100%;max-width:none}.bc-card{padding:16px}.bc-filter{padding:8px}.bc-reference{gap:7px;flex-wrap:wrap}}
'''
text = text.replace('</style>', css+'</style>', 1)
path.write_text(text, encoding='utf-8')
