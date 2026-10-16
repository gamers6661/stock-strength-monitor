from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def replace_function(text,start,end,new):
    left=text.index(start);right=text.index(end,left)
    return text[:left]+new+'\n'+text[right:]
path=ROOT/'radar_ui.js';s=path.read_text(encoding='utf-8')
s=s.replace("axis:'trend',scope:'trend',sort:'trend'","axis:'both',scope:'all',sort:'board',rankBoardId:''",1)
s=s.replace("var MS_VIEW={stocks:msStockDefaults(),", "var MS_VIEW={stocks:msStockDefaults(),radar:msStockDefaults(),",1)
s=s.replace("function msMatchDirections(r){var v=MS_VIEW.stocks", "function msMatchDirections(r,key){var v=MS_VIEW[key||'stocks']",1)
s=s.replace("function msRows(key,axis){\n", "function msRows(key,axis){\n if(key==='radar')return mtRows();\n if(key==='stocks'&&DATA.stock_board_ranking)return msRankRows();\n",1)
s=s.replace("if(field==='scope'){", "if(key==='stocks'&&DATA.stock_board_ranking){v.limit=100;msRender(key);return;}\n if(field==='scope'){",1)
a=s.index('function msToggleBoard(');b=s.index('function msSelect(',a)
s=s[:a]+r"""function msToggleBoard(id,key){key=key||'stocks';var b=boardById(id);if(!b)return;var v=MS_VIEW[key],field=b.type==='industry'?'industryIds':'themeIds',i=v[field].indexOf(id);if(i>=0)v[field].splice(i,1);else v[field].push(id);v.limit=100;if(key==='stocks'){v.scope='all';v.rankBoardId=id;}msRender(key);}
function msClearDirections(key){key=key||'stocks';if(key==='stocks')STATE.boardFilterId=null;var v=MS_VIEW[key];v.industryIds=[];v.themeIds=[];v.boardQuery='';v.rankBoardId='';msRender(key);}
function msOpenStocks(id,axis,allMembers){resetMSMemberView();var v=MS_VIEW.stocks;v.axis=axis||'both';v.sort='board';v.scope=DATA.stock_board_ranking?'all':allMembers?'all':axis||'focus';if(id){var b=boardById(id);if(b){v[b.type==='industry'?'industryIds':'themeIds']=[id];v.rankBoardId=id;v.openKinds[b.type]=true;}}closeDrawer();RENDERED.stocks=false;goPane('stocks');renderStocks();}
"""+s[b:]
a=s.index('function msDirectionPicker(');b=s.index('function msScore(',a)
picker=s[a:b].replace('function msDirectionPicker(){var v=MS_VIEW.stocks',"function msDirectionPicker(key){key=key||'stocks';var v=MS_VIEW[key]")
picker=picker.replace('msClearDirections()',"msClearDirections(\\''+key+'\\')")
picker=picker.replace('msToggleBoard(\\\'', 'msToggleBoard(\\\'') # Dynamic key is appended below.
picker=picker.replace("+jsq(id)+'\\\')", "+jsq(id)+'\\\',\\\''+key+'\\\')")
picker=picker.replace("+jsq(b.id)+'\\\')", "+jsq(b.id)+'\\\',\\\''+key+'\\\')")
picker=picker.replace('data-ms-search-key="stocks"', 'data-ms-search-key="\'+key+\'"')
picker=picker.replace("msSearchInput(event,this,\\'stocks\\',\\'boardQuery\\')", "msSearchInput(event,this,\\''+key+'\\',\\'boardQuery\\')")
picker=picker.replace("MS_VIEW.stocks.browseOpen", "MS_VIEW[\\''+key+'\\'].browseOpen")
picker=picker.replace("MS_VIEW.stocks.openKinds", "MS_VIEW[\\''+key+'\\'].openKinds")
s=s[:a]+picker+s[b:]
s=s.replace("function msTools(key){var v=MS_VIEW[key],h='';", "function msTools(key){if(key==='stocks'&&DATA.stock_board_ranking)return msRankTools();var v=MS_VIEW[key],h='';",1)
s=s.replace("function msTable(rows,key,limit){var boards=", "function msTable(rows,key,limit){if(key==='stocks'&&DATA.stock_board_ranking)return msRankTable(rows,limit);var boards=",1)
s=s.replace("function msRender(key){\n", "function msRender(key){\n if(key==='radar')return mtRender();\n",1)
s=s.replace("var description=key==='stocks'?", "var description=key==='stocks'&&DATA.stock_board_ranking?'展示所选方向的完整主板成员，趋势与情绪分别标注。排名以当前板块为比较范围，数据缺失保留在末尾。':key==='stocks'?",1)
s=s.replace("沪深主板 · 趋势与情绪独立排名 · 行业 / 题材多选筛选", "沪深主板 · 板块完整成员排名 · 趋势 / 情绪双标签",1)
s=s.replace("function msCSV(key){var rows=msRows(key);", "function msCSV(key){if(key==='radar')return mtCSV();if(key==='stocks'&&DATA.stock_board_ranking)return msRankCSV();var rows=msRows(key);",1)
path.write_text(s,encoding='utf-8')
path=ROOT/'ma_trend_ui.js';s=path.read_text(encoding='utf-8')
# Only the MA radar owns the independent radar state. Stock membership ranking is independent.
s=s.replace('MS_VIEW.stocks','MS_VIEW.radar')
s=s.replace("msMatchDirections(r)","msMatchDirections(r,'radar')")
s=s.replace("  if(STATE.boardFilterId){var b=boardById(STATE.boardFilterId);if(b&&(b.member_codes||[]).indexOf(r.code)<0)return false;}\n",'')
a=s.index('function mtTools(');b=s.index('function mtTable(',a)
s=s[:a]+r"""function mtTools(){var v=MS_VIEW.radar;return '<div class="ms-toolbar">'+
 msSelect('scope',[['trend','有效观察'],['advance','推进延续'],['startup_pending','启动待确认'],['displaced','位置 / 结构偏离'],['repair','支撑修复观察'],['exited','已退出'],['pending','数据待核验'],['all','全部成员']],'radar','趋势观察范围')+
 msSelect('phase',[['','全部阶段'],['5','MA5初期推进'],['10','MA10承接整理'],['20','MA20横盘再启动'],['底部反弹','底部反弹'],['快速收回','快速收回']],'radar','均线阶段')+
 '<input aria-label="雷达股票搜索" placeholder="代码 / 名称" value="'+esc(v.q)+'" data-ms-search-key="radar" data-ms-search-field="q" oninput="msSearchInput(event,this,\'radar\',\'q\')"><button class="btn" onclick="mtCSV()">导出当前雷达 CSV</button></div>';}
function mtOpen(id,phase){var v=MS_VIEW.radar;v.scope='trend';v.phase=String(phase||'');v.industryIds=[];v.themeIds=[];v.boardQuery='';v.q='';if(id){var b=boardById(id);if(b)v[b.type==='industry'?'industryIds':'themeIds']=[id];}closeDrawer();RENDERED.radar=false;goPane('radar');mtRender();}
function renderRadar(){MS_VIEW.radar.axis='trend';if(MS_VIEW.radar.scope==='all'&&!MS_VIEW.radar.initialized)MS_VIEW.radar.scope='trend';MS_VIEW.radar.initialized=true;mtRender();}
function mtCSV(){return msExportRows(mtRows(),'radar','均线雷达_'+DATA.ui_generation+'.csv');}
"""+s[b:]
s=s.replace("document.getElementById('ms-stock-host')","document.getElementById('ma-radar-host')")
s=s.replace("'#p-stocks h1'","'#p-radar h1'").replace("'stk-sub'","'radar-sub'")
s=s.replace('msDirectionPicker()+mtTools()',"msDirectionPicker('radar')+mtTools()")
s=s.replace("msRender(\\'stocks\\')","msRender(\\'radar\\')")
s=s.replace("label==='强势搜索'", "label==='雷达股票搜索'")
s=s.replace('MA20以锁定的平台底部防守；失守15个交易分钟未修复退出。','MA5有效失守转MA10；MA10有效失守须已有合格MA20平台，否则退出。MA20以锁定的平台底部防守。')
s=s.replace("'近期放量上攻或有效突破，沿MA5运行'","'放量上攻、有效突破或涨停突破，沿MA5运行'")
s=s.replace("'前期强势后，MA10附近整理与底部反弹'","'MA5失守后转入承接；紧缩平台形成与底部反弹单列'")
s=s.replace("onclick=\"msOpenStocks(null,\\'trend\\')\"", "onclick=\"mtOpen()\"")
s=s.replace("onclick=\"msOpenStocks(null,\\'trend\\');MS_VIEW.radar.phase=\\''+n+'\\';msRender(\\'radar\\')\"", "onclick=\"mtOpen(null,'+n+')\"")
s=s.replace("onclick=\"msOpenStocks(\\''+jsq(b.id)+'\\',\\'trend\\')\"", "onclick=\"mtOpen(\\''+jsq(b.id)+'\\')\"")
a=s.index('var MT_OLD_ROWS=');s=s[:a]+r"""var MT_OLD_OVERVIEW=renderOverview,MT_OLD_STOCK=showStock,MT_OLD_DETAIL=msDetail;
renderOverview=function(){return mtModel()?mtOverview():MT_OLD_OVERVIEW();};
msDetail=function(m){var h=MT_OLD_DETAIL(m);return mtModel()?'<details class="card"><summary>历史收益力度与情绪分 · 独立参考</summary>'+h+'</details>':h;};
showStock=function(code,boardId){var result=MT_OLD_STOCK(code,boardId),row=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).filter(function(r){return r.code===code;})[0],host=document.getElementById('dr-b');if(mtModel()&&row&&row.ma_trend&&host){host.insertAdjacentHTML('beforeend',mtDetail(row.ma_trend));var title=host.querySelector('h3');if(title)title.insertAdjacentHTML('afterend','<p class="ms-muted ma-detail-badge">'+msTag(row.ma_trend.stage_label,row.ma_trend.reason)+' '+msTag(mtSnapshotFresh(row.ma_trend)?row.ma_trend.status:'快照已过期',row.ma_trend.reason)+' · 源行情 '+esc(row.ma_trend.quote_at||'待核验')+'</p>');}return result;};
if(typeof renderFresh==='function'){var MT_OLD_FRESH=renderFresh,MT_FRESH_KEY=null;renderFresh=function(){MT_OLD_FRESH();if(!mtModel())return;var key=(DATA.ui_generation||'')+':'+(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).filter(function(r){return r.ma_trend&&r.ma_trend.eligible&&mtSnapshotFresh(r.ma_trend);}).length;if(MT_FRESH_KEY!==null&&key!==MT_FRESH_KEY){if(STATE.pane==='radar')mtRender();if(STATE.pane==='stocks')msRender('stocks');renderOverview();}MT_FRESH_KEY=key;};}
"""
# Honest date names and chronology; raw JSON remains available in the folded detail.
s=s.replace('强势起点 / 量价','本轮启动 / 最近确认')
s=s.replace("esc(o.date||'—')+' · '+esc(o.basis||'')", "esc(o.date||'—')+'启动 · 最近确认 '+esc((m.last_confirmation||{}).date||o.date||'—')")
s=s.replace("<p>强势起点 ","<p>本轮强势启动 ")
s=s.replace("</p><p>单日上涨 ","</p><p>最近强势确认 '+esc((m.last_confirmation||{}).date||o.date||'—')+' · 实际覆盖 '+(m.history_days||'—')+' 个完成交易日（'+esc(m.history_from||'—')+' 至 '+esc(m.asof||'—')+'）</p><p>阶段转换 '+esc((m.transitions||[]).map(function(t){return (t.at||t.date)+' MA'+t.from_stage+'→MA'+t.to_stage;}).join('；')||'暂无')+'</p><p>单日上涨 ",1)
s=s.replace("失守 '+p.repair_minutes+' 个交易分钟未收回退出；", "失守 '+p.repair_minutes+' 个交易分钟未收回：MA5转MA10，MA10无合格MA20平台则退出，MA20平台失守退出；")
s=s.replace("<b class=\"ma-state '+(m.eligible?'ma-active':'ma-inactive')+'\">", "<b '+msTipAttrs(m.status,m.reason)+' class=\"ma-state '+(m.eligible?'ma-active':'ma-inactive')+'\">")
s=s.replace("<span class=\"cd\">'+esc(m.stage_label||'暂无合格阶段')", "<span '+msTipAttrs(m.stage_label,m.structure_state)+' class=\"cd\">'+esc(m.stage_label||'暂无合格阶段')")
path.write_text(s,encoding='utf-8')
path=ROOT/'dashboard_template.html';s=path.read_text(encoding='utf-8')
s=s.replace('<button data-p="stocks">个股</button>','<button data-p="stocks">个股</button>\n      <button data-p="radar">选股雷达</button>',1)
s=s.replace('<!-- ══════ 板块 ══════ -->','<!-- ══════ 均线选股雷达 ══════ -->\n<section class="pane" id="p-radar"><div class="hero"><h1>选股雷达</h1><p id="radar-sub">均线趋势三阶段观察</p></div><div class="main" style="padding-top:0"><div id="ma-radar-host"></div></div></section>\n\n<!-- ══════ 板块 ══════ -->',1)
s=s.replace("  if(p==='radar')p='stocks';\n",'')
s=s.replace("    if(p==='stocks')renderStocks();", "    if(p==='stocks')renderStocks();\n    if(p==='radar')renderRadar();",1)
s=s.replace('    renderStocks();renderOverview();','    renderStocks();if(STATE.pane===\'radar\')renderRadar();renderOverview();',1)
s=s.replace('</style>', '.ms-label-tooltip{position:fixed;z-index:10000;max-width:360px;padding:10px 13px;background:#17243b;color:#fff;border-radius:9px;font-size:12px;line-height:1.65;box-shadow:0 5px 22px #0003;pointer-events:none;white-space:normal}.ms-label-tooltip[hidden]{display:none}[data-tip]{cursor:help}[data-tip]:focus-visible{outline:2px solid #4686cf;outline-offset:2px}#p-radar .hero{padding-bottom:20px}.ma-trend-table td{white-space:normal}.ms-rank-table .ms-tag-list{max-width:280px}\n</style>',1)
path.write_text(s,encoding='utf-8')
path=ROOT/'ui_client.js';s=path.read_text(encoding='utf-8').replace('stocks:renderStocks,boards:renderBoards','stocks:renderStocks,radar:renderRadar,boards:renderBoards',1);path.write_text(s,encoding='utf-8')
print('Updated independent radar navigation, state and full member rank hooks')
