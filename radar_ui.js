/* Rankings and strength judgments are backend results. UI only selects confirmed members. */
function msStockDefaults(){return {axis:'both',scope:'all',sort:'board',rankBoardId:'',phase:'',q:'',limit:100,industryIds:[],themeIds:[],boardQuery:'',openKinds:{},browseOpen:false};}
var MS_VIEW={stocks:msStockDefaults(),radar:msStockDefaults(),industry:{scope:'focus',sort:'trend',phase:'',q:'',limit:100},theme:{scope:'focus',sort:'trend',phase:'',q:'',limit:100}};
var MS_REL_DATA=null,MS_REL={};
// Official board entries and F10 stock classifications are separate views.
function msOfficialBoard(b){
 if(!b)return false;if(b.catalog_listed===true)return true;
 // Some official concepts appear only in the directory's index mapping.
 var idx=b.index_trend||b.index_current||{};
 return b.type==='theme'&&idx.name===b.name&&/^88[56]\d{3}$/.test(String(idx.code||''))&&String(idx.source||'').indexOf('同花顺概念指数')===0;
}
function msBoardCatalog(){return (DATA.board_catalog||[]).filter(msOfficialBoard);}
boardCatalog=msBoardCatalog;
function msModel(){return DATA.market_strength||{};}
function msRelations(code){
 if(MS_REL_DATA!==DATA){MS_REL_DATA=DATA;MS_REL={};msBoardCatalog().forEach(function(b){(b.member_codes||[]).forEach(function(c){(MS_REL[c]||(MS_REL[c]=[])).push(b);});});}
 return MS_REL[code]||[];
}
function msMatchDirections(r,key){var v=MS_VIEW[key||'stocks'],relations=msRelations(r.code).map(function(b){return b.id;});
 return (!v.industryIds.length||v.industryIds.some(function(id){return relations.indexOf(id)>=0;}))&&(!v.themeIds.length||v.themeIds.some(function(id){return relations.indexOf(id)>=0;}));
}
function msRows(key,axis){
 if(key==='radar')return mtRows();
 if(key==='stocks'&&DATA.stock_board_ranking)return msRankRows();
 var v=MS_VIEW[key],boards=key==='industry'||key==='theme',src=boards?msBoardCatalog():(DATA.stocks||[]).concat(DATA.coverage_catalog||[]),map={};
 src.forEach(function(r){map[boards?r.id:r.code]=r;});
 var lists=msModel()[boards?'boards':'stocks']||{},sort=axis||v.sort,ids=(lists.sorts||{})[sort]||lists.all||[],scope=v.scope;
 var included={};(lists[scope]||[]).forEach(function(c){included[c]=true;});if(sort==='day_attack')ids=lists.day_attack||[];
 return ids.map(function(c){return map[c];}).filter(function(r){
  if(!r||!included[boards?r.id:r.code]||boards&&r.type!==key)return false;
  if(key==='stocks'&&STATE.boardFilterId){var b=boardById(STATE.boardFilterId);if(b&&(b.member_codes||[]).indexOf(r.code)<0)return false;}
  if(key==='stocks'&&!msMatchDirections(r))return false;
  var m=r.market_strength||{},tags=(m.labels||[]).concat(m.events||[],m.phase||[]);
  return (!v.phase||tags.indexOf(v.phase)>=0)&&(!v.q||String((r.code||'')+' '+r.name).indexOf(v.q)>=0);
 });
}
function msUpdate(key,field,value){var v=MS_VIEW[key];v[field]=value;
 if(key==='stocks'&&DATA.stock_board_ranking){v.limit=100;msRender(key);return;}
 if(field==='scope'){v.sort=value==='day_attack'?'day_attack':key==='stocks'?v.axis:value==='emotion'?'emotion':'trend';}
 v.limit=100;msRender(key);
}
// Keep the composing input alive through compositionend and its trailing input event.
function msSearchStart(input){clearTimeout(input._msCommitTimer);input._msComposing=true;input._msEnding=false;}
function msSearchInput(event,input,key,field){
 MS_VIEW[key][field]=input.value;
 if(event.isComposing||input._msComposing||input._msEnding)return;
 msUpdate(key,field,input.value);
}
function msSearchEnd(input,key,field){
 input._msComposing=false;input._msEnding=true;
 clearTimeout(input._msCommitTimer);
 input._msCommitTimer=setTimeout(function(){input._msEnding=false;msUpdate(key,field,input.value);},0);
}
document.addEventListener('compositionstart',function(event){var input=event.target;if(input.getAttribute&&input.getAttribute('data-ms-search-key'))msSearchStart(input);});
document.addEventListener('compositionend',function(event){var input=event.target,key=input.getAttribute&&input.getAttribute('data-ms-search-key');if(key)msSearchEnd(input,key,input.getAttribute('data-ms-search-field'));});
function msStockAxis(axis){var v=MS_VIEW.stocks;v.axis=axis;if(v.scope==='trend'||v.scope==='emotion')v.scope=axis;v.sort=v.scope==='day_attack'?'day_attack':axis;v.limit=100;msRender('stocks');}
function msStockAll(checked){MS_VIEW.stocks.scope=checked?'all':MS_VIEW.stocks.axis;MS_VIEW.stocks.sort=MS_VIEW.stocks.axis;MS_VIEW.stocks.limit=100;msRender('stocks');}
function msToggleBoard(id,key){key=key||'stocks';var b=boardById(id);if(!b)return;var v=MS_VIEW[key],field=b.type==='industry'?'industryIds':'themeIds',i=v[field].indexOf(id);if(i>=0)v[field].splice(i,1);else v[field].push(id);v.limit=100;if(key==='stocks'){v.scope='all';v.rankBoardId=id;}msRender(key);}
function msClearDirections(key){key=key||'stocks';if(key==='stocks')STATE.boardFilterId=null;var v=MS_VIEW[key];v.industryIds=[];v.themeIds=[];v.boardQuery='';v.rankBoardId='';msRender(key);}
function msOpenStocks(id,axis,allMembers){resetMSMemberView();var v=MS_VIEW.stocks;v.axis=axis||'both';v.sort='board';v.scope=DATA.stock_board_ranking?'all':allMembers?'all':axis||'focus';if(id){var b=boardById(id);if(b){v[b.type==='industry'?'industryIds':'themeIds']=[id];v.rankBoardId=id;v.openKinds[b.type]=true;}}closeDrawer();RENDERED.stocks=false;goPane('stocks');renderStocks();}
function msSelect(field,opts,key,label){var v=MS_VIEW[key];return '<select aria-label="'+label+'" onchange="msUpdate(\''+key+'\',\''+field+'\',this.value)">'+opts.map(function(x){return '<option value="'+x[0]+'" '+(v[field]===x[0]?'selected':'')+'>'+x[1]+'</option>';}).join('')+'</select>';}
function msTools(key){if(key==='stocks'&&DATA.stock_board_ranking)return msRankTools();var v=MS_VIEW[key],h='';
 if(key==='stocks')h='<div class="ms-style-tabs" role="tablist" aria-label="个股风格"><button role="tab" aria-selected="'+(v.axis==='trend')+'" class="ms-tab '+(v.axis==='trend'?'on':'')+'" onclick="msStockAxis(\'trend\')">趋势榜</button><button role="tab" aria-selected="'+(v.axis==='emotion')+'" class="ms-tab emotion '+(v.axis==='emotion'?'on':'')+'" onclick="msStockAxis(\'emotion\')">情绪榜</button></div>';
 h+='<div class="ms-toolbar">';
 if(key==='stocks')h+=msSelect('scope',[[v.axis,'当前榜强势'],['focus','任一强势'],['both','仅看双强'],['all','全部成员'],['day_attack','当日异动']],key,'筛选范围');

 else h+=msSelect('scope',[['focus','全部强势'],['trend','趋势强'],['emotion','情绪强'],['all','全部板块']],key,'强势范围')+msSelect('sort',[['trend','趋势排序'],['emotion','情绪排序']],key,'强势排序');
 h+=msSelect('phase',[['','全部个性标签'],['新进入强势','新进入强势'],['突破','突破'],['再启动','再启动'],['趋势推进','趋势推进'],['回踩整理','回踩整理'],['情绪进攻','情绪进攻'],['明显回落','明显回落']],key,'个性标签')+'<input aria-label="强势搜索" placeholder="代码 / 名称" value="'+esc(v.q)+'" data-ms-search-key="'+key+'" data-ms-search-field="q" oninput="msSearchInput(event,this,\''+key+'\',\'q\')"><button class="btn" onclick="msCSV(\''+key+'\')">导出当前结果 CSV</button></div>';return h;
}
function msDirectionPicker(key){key=key||'stocks';var v=MS_VIEW[key],selected=v.industryIds.concat(v.themeIds),q=v.boardQuery||'';
 var h='<section class="card ms-direction-picker"><div class="ms-section-head"><div><h3>按板块 / 题材选股</h3><p class="ms-muted">同花顺官方板块 · 确认成员 · 同类多选取并集，行业与题材取交集</p></div><button class="btn ms-clear-button" onclick="msClearDirections(\''+key+'\')">清除方向</button></div><div class="ms-direction-search-wrap"><input class="ms-direction-search" aria-label="搜索板块题材" placeholder="搜索行业或题材名称" value="'+esc(q)+'" data-ms-search-key="'+key+'" data-ms-search-field="boardQuery" oninput="msSearchInput(event,this,\''+key+'\',\'boardQuery\')"></div>';
 h+='<div class="ms-selected-directions">'+(selected.length?selected.map(function(id){var b=boardById(id);return '<button class="ms-chip selected" onclick="msToggleBoard(\''+jsq(id)+'\',\''+key+'\')">'+esc(b?b.name:id)+' ×</button>';}).join(''):'<span class="ms-muted">未选择方向 · 按当前筛选范围展示股票</span>')+'</div>';
 h+='<details class="ms-direction-browser" '+(q||v.browseOpen?'open':'')+'><summary onclick="MS_VIEW[\''+key+'\'].browseOpen=!this.parentNode.open">浏览行业 / 题材 <span>展开目录</span></summary><div class="ms-direction-browser-content">';
 ['industry','theme'].forEach(function(kind){var rows=msBoardCatalog().filter(function(b){return b.type===kind&&(!q||b.name.indexOf(q)>=0);}),rank=((msModel().boards||{}).sorts||{}).trend||[],order={};rank.forEach(function(id,i){order[id]=i;});rows.sort(function(a,b){return (order[a.id]==null?1e9:order[a.id])-(order[b.id]==null?1e9:order[b.id]);});
  h+='<details '+(q||v.openKinds[kind]?'open':'')+' class="ms-direction-options"><summary onclick="MS_VIEW[\''+key+'\'].openKinds[\''+kind+'\']=!this.parentNode.open">'+ (kind==='industry'?'行业':'题材')+' · '+rows.length+' 个方向</summary><div class="ms-chip-list">'+rows.map(function(b){var on=selected.indexOf(b.id)>=0;return '<button aria-pressed="'+on+'" class="ms-chip '+(on?'selected':'')+'" onclick="msToggleBoard(\''+jsq(b.id)+'\',\''+key+'\')">'+esc(b.name)+'</button>';}).join('')+'</div></details>';
 });return h+'</div></details></section>';
}
function msScore(m,axis){return m[axis+'_score']==null?'—':fmt(m[axis+'_score'],1)+' · '+esc(m[axis+'_level']||'—');}
function msBadge(m,axis){return '<span '+msTipAttrs(axis==='trend'?'趋势力度':'情绪强度',(m.reasons||[]).join('；'))+' class="ms-badge ms-'+axis+' '+(m[axis+'_score']>=65?'ms-hot':'')+'">'+(axis==='trend'?'趋势力度 ':'情绪 ')+msScore(m,axis)+'</span>';}
function msHistory(m,n){var r=(m.history_returns||{})[n];return r==null?'—':pctHtml(r,2);}
function msTags(m){return (m.labels||m.events||[]).map(function(t){return msTag(t,(m.reasons||[]).join('；'),t==='明显回落'?'risk':'');}).join('')||'<span class="ms-muted">暂无新增形态标签</span>';}
function msAffiliation(r,key){var rel=msRelations(r.code),v=MS_VIEW.stocks,selected=v.industryIds.concat(v.themeIds),matched=key==='stocks'?rel.filter(function(b){return selected.indexOf(b.id)>=0;}):[],themes=rel.filter(function(b){return b.type==='theme';}),industry=r.industry_detail||r.industry||'行业未收录';
 var h='<div class="ms-affiliation"><span class="ms-industry">'+esc(industry)+'</span>';
 if(matched.length)h+='<div class="ms-match">匹配方向：'+matched.map(function(b){return esc(b.name);}).join(' / ')+'</div>';
 var display=themes.slice(0,2);h+=display.map(function(b){return '<button class="ms-chip small" onclick="event.stopPropagation();msOpenStocks(\''+jsq(b.id)+'\')">'+esc(b.name)+'</button>';}).join('');
 if(themes.length>2)h+='<details onclick="event.stopPropagation()"><summary>+'+(themes.length-2)+' 个题材</summary><div class="ms-chip-list">'+themes.slice(2).map(function(b){return '<button class="ms-chip small" onclick="event.stopPropagation();msOpenStocks(\''+jsq(b.id)+'\')">'+esc(b.name)+'</button>';}).join('')+'</div></details>';
 return h+'</div>';
}
function msMore(rows,shown,key){return (rows.length>shown.length?'<button class="btn" onclick="MS_VIEW[\''+key+'\'].limit+=100;msRender(\''+key+'\')">加载更多（完整 '+rows.length+' 项）</button>':'')+(!rows.length?'<p class="empty">暂无符合条件的股票或方向，可调整当前筛选。</p>':'');}
function msTable(rows,key,limit){if(key==='stocks'&&DATA.stock_board_ranking)return msRankTable(rows,limit);var boards=key==='industry'||key==='theme',shown=limit?rows.slice(0,limit):rows,axis=key==='stocks'?MS_VIEW.stocks.axis:null;
 var ranked=key==='stocks',h='<div class="tw"><table class="market-strength-table ms-research-table"><thead><tr>'+(ranked?'<th class="ms-rank-heading">排名</th>':'')+'<th class="l">名称 / 所属方向</th><th>当日涨幅</th><th>趋势强度</th><th>情绪强度</th><th>'+ (axis==='emotion'?'进攻 / 保持 / 活跃':'历史5 / 10 / 20日')+'</th><th class="l">结构 / 个性标签</th></tr></thead><tbody>';
 shown.forEach(function(r,i){var m=r.market_strength||{},chg=boards?(m.emotion_parts||{}).R0:r.change_pct,ev=m.display_evidence||{},recent=m.recent_emotion||{};
 var metric=axis==='emotion'?'<b>'+fmt(m.day_attack,1)+' / '+fmt(ev.hold,1)+' / '+(recent.active_days==null?'—':recent.active_days+'/5')+'</b><span class="cd">完成日5日 '+msHistory(m,5)+'</span>':[5,10,20].map(function(n){return '<span class="ms-return '+(m.dominant_period===n?'dominant':'')+'">'+n+'日 '+msHistory(m,n)+'</span>';}).join('');
 h+='<tr data-strength-id="'+esc(r.id||r.code)+'" class="clickable" onclick="'+(boards?'showBoardById(\''+jsq(r.id)+'\')':'showStock(\''+jsq(r.code)+'\')')+'">'+(ranked?'<td class="ms-rank-cell"><span class="ms-rank '+(i<3?'podium rank-'+(i+1):'')+'">'+(i+1)+'</span></td>':'')+'<td class="l"><b>'+esc(r.name||r.code)+'</b><span class="cd">'+esc(r.code||'')+'</span>'+(boards?'':msAffiliation(r,key))+'</td><td>'+pctHtml(chg,2)+'</td><td>'+msBadge(m,'trend')+'</td><td>'+msBadge(m,'emotion')+'</td><td class="ms-metric-cell">'+metric+'</td><td class="l"><span class="cd">'+esc((m.background||{}).label||'')+' · '+esc(ev.structure||'')+'</span><div class="ms-tag-list">'+msTags(m)+'</div><span class="ms-card-risk">'+esc((m.risks||[]).slice(0,1).join('；'))+'</span></td></tr>';
 });return h+'</tbody></table></div>'+msMore(rows,shown,key);
}
function msStamp(){var m=msModel();return esc(m.mode||'')+' · 行情截至 '+esc(String((DATA.direction_changes||{}).source_at||m.at||'—').slice(0,19))+' · 沪深主板';}
function msDelta(value,digits){return value==null?'—':(value>0?'+':'')+fmt(value,digits);}
function msRender(key){
 if(key==='radar')return mtRender();
 var host=document.getElementById(key==='industry'?'board-center':key==='theme'?'theme-center':'ms-stock-host'),focused=document.activeElement;
 if(host&&focused&&host.contains(focused)&&(focused._msComposing||focused._msEnding))return;
 var v=MS_VIEW[key],rows=msRows(key),html=key==='stocks'?msDirectionPicker():'';
 html+=msTools(key);
 var description=key==='stocks'&&DATA.stock_board_ranking?'展示所选方向的完整主板成员，趋势与情绪分别标注。排名以当前板块为比较范围，数据缺失保留在末尾。':key==='stocks'?(v.scope==='day_attack'?'按当日进攻强度排序；当日异动不等于趋势强或情绪强。':v.axis==='trend'?'历史上涨力度与结构决定趋势排名；当天大涨不是入榜要求。':'当日进攻、区间保持与近期活跃决定情绪排名；不要求历史趋势强。'):'同花顺确认成员共振；官方指数在详情中单列。';
 html+='<p class="ms-muted">'+description+' 当前 '+rows.length+' 项。</p>'+msTable(rows,key,v.limit);
 if(host){var label=focused&&focused.getAttribute('aria-label'),start=focused&&focused.selectionStart,end=focused&&focused.selectionEnd;if(typeof msHideTooltip==='function')msHideTooltip();host.innerHTML=html;if(label==='强势搜索'||label==='搜索板块题材'){var next=host.querySelector('[aria-label="'+label+'"]');if(next){next.focus({preventScroll:true});if(start!=null)next.setSelectionRange(start,end);}}}
}
function renderBoards(){document.getElementById('bd-metrics').innerHTML='<div class="card"><h3>行业强度</h3><p>'+msStamp()+'</p></div>';msRender('industry');}
function renderThemesPage(){msRender('theme');}
function renderStocks(){document.getElementById('stk-sub').textContent=msStamp();var stockHeading=document.querySelector('#p-stocks h1');if(stockHeading)stockHeading.textContent='个股强度榜';var oldSearch=document.querySelector('#p-stocks .search');if(oldSearch)oldSearch.style.display='none';var table=document.getElementById('tb-stocks'),res=document.getElementById('stk-res');
 if(!document.getElementById('ms-stock-host')){var host=document.createElement('div');host.id='ms-stock-host';var tableWrap=table.parentNode;tableWrap.parentNode.insertBefore(host,tableWrap);tableWrap.style.display='none';}
 var legacyToolbar=document.querySelector('#p-stocks .toolbar');if(legacyToolbar)legacyToolbar.style.display='none';
 res.innerHTML='沪深主板 · 板块完整成员排名 · 趋势 / 情绪双标签';
 ['stk-more','stock-view-tabs','stock-views','stk-view-tabs','btn-filter','btn-export','q'].forEach(function(id){var e=document.getElementById(id);if(e)e.style.display='none';});
 var only=document.getElementById('btn-only-view');if(only){only.textContent='清除成员筛选';only.style.display='none';only.onclick=clearMSMembers;}
 if(STATE.q){MS_VIEW.stocks.q=STATE.q;MS_VIEW.stocks.scope='all';}msRender('stocks');
}
function msDirectionCard(b,axis){var m=b.market_strength||{},share=(m.member_strength||{})[axis+'_pct'],r0=(m.emotion_parts||{}).R0,dc=m.direction_change,a=dc&&dc.axes&&dc.axes[axis],lists=msModel().stocks||{},lookup={};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(r){lookup[r.code]=r;});var leaders=(((lists.sorts||{})[axis])||[]).filter(function(c){return (b.member_codes||[]).indexOf(c)>=0&&lookup[c]&&(lookup[c].market_strength||{})[axis+'_strong'];}).slice(0,3);
 return '<article class="ms-direction-card '+axis+'" data-board-id="'+esc(b.id)+'" data-axis="'+axis+'"><div class="ms-card-head"><button class="ms-name-link" onclick="msOpenStocks(\''+jsq(b.id)+'\',\''+axis+'\')">'+esc(b.name)+'</button><button class="ms-detail-link" onclick="showBoardById(\''+jsq(b.id)+'\')">详情 ↗</button></div>'+msBadge(m,axis)+'<div class="ms-mini-metrics"><span>成员整体涨幅<b>'+pctHtml(r0,2)+'</b></span><span>'+ (axis==='trend'?'趋势':'情绪')+'强股占比<b>'+fmt(share,1)+'%</b></span></div>'+(a?'<p class="ms-muted">较 '+esc(dc.from_at.slice(11,16))+' · 成员涨幅 '+msDelta(dc.return_delta_pp,2)+'个百分点 · 强股占比 '+msDelta(a.share_delta_pp,1)+'个百分点</p>':'')+'<div class="ms-leaders">'+leaders.map(function(c){return '<button onclick="showStock(\''+jsq(c)+'\')">'+esc(lookup[c].name)+'</button>';}).join('')+'</div></article>';
}
function renderOverview(){document.getElementById('hero-h1').textContent='今天重点看哪里';document.getElementById('hero-p').textContent='市场温度 · 趋势与情绪集中方向 · 最新行情中的转强变化';document.getElementById('hero-stamp').textContent=msStamp();
 ['ov-work-live','ov-work-close','overview-more'].forEach(function(id){var e=document.getElementById(id);if(e)e.style.display='none';});var sw=document.querySelector('#p-overview .work-switch');if(sw)sw.style.display='none';
 var host=document.getElementById('ms-overview-host');if(!host){host=document.createElement('div');host.id='ms-overview-host';document.querySelector('#p-overview .main').prepend(host);}
 var meta=msModel(),counts=meta.counts||{},breadth=DATA.breadth||{},temperature=DATA.market_emotion||{},bl={};msBoardCatalog().forEach(function(b){bl[b.id]=b;});var dc=DATA.direction_changes||{},pool=(meta.coverage||{}).pool||0;
 var metrics=[['上涨占比',fmt(breadth.up_ratio,1)+'%'],['涨停 / 跌停',(temperature.limit_up||0)+' / '+(temperature.limit_down||0)],['昨日涨停股表现',pctHtml(temperature.yesterday_limit_median_pct,2)],['趋势强 / 情绪强',(counts.trend||0)+' / '+(counts.emotion||0)]];
 var h='<section class="card ms-overview-section"><div class="ms-section-head"><h3>市场温度</h3><span class="ms-muted">沪深主板 · '+(temperature.traded||breadth.traded||0)+'只成交</span></div><div class="ms-temperature-grid">'+metrics.map(function(x){return '<div><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>';}).join('')+'</div><p class="ms-muted">股票池 '+pool+' 只 · 趋势强占比 '+fmt(pool?100*(counts.trend||0)/pool:null,1)+'% · 情绪强占比 '+fmt(pool?100*(counts.emotion||0)/pool:null,1)+'%'+(dc.temperature_change?' · 较 '+esc(dc.from_at.slice(11,16))+' 可比样本上涨占比变化 '+msDelta(dc.temperature_change.up_ratio_delta_pp,1)+'个百分点':'')+'</p></section>';
 h+='<section class="card ms-overview-section"><div class="ms-section-head"><h3>正在转强</h3><span class="ms-muted">'+(dc.from_at?'比较 '+esc(dc.from_at.slice(11,19))+' → '+esc(dc.source_at.slice(11,19)):'依据同日可比行情变化')+'</span></div>';
 var changes=(dc.items||[]).slice(0,6);h+=changes.length?'<div class="ms-turning-grid">'+changes.map(function(x){return '<button class="ms-turning-card '+x.axis+'" onclick="msOpenStocks(\''+jsq(x.id)+'\',\''+x.axis+'\')"><b>'+esc(x.name)+'</b><span>'+ (x.axis==='trend'?'趋势':'情绪')+' · '+esc(x.kind)+'</span><small>成员涨幅 '+msDelta(x.return_delta_pp,2)+'个百分点 · 强股占比 '+msDelta(x.share_delta_pp,1)+'个百分点</small></button>';}).join('')+'</div>':'<p class="ms-muted">'+(dc.from_at?'本次可比行情中暂无符合转强条件的方向。':'暂无同日可比行情变化记录；下面展示最新强势方向。')+'</p>';h+='</section>';
 ['trend','emotion'].forEach(function(axis){var lists=meta.boards||{},ids=((lists.sorts||{})[axis]||[]).filter(function(id){return (lists[axis]||[]).indexOf(id)>=0;});h+='<section class="card ms-overview-section"><div class="ms-section-head"><h3>'+(axis==='trend'?'趋势集中方向':'情绪集中方向')+'</h3><button class="btn" onclick="msOpenStocks(null,\''+axis+'\')">查看对应强势股 →</button></div><div class="ms-direction-columns">';['industry','theme'].forEach(function(kind){var rows=ids.map(function(id){return bl[id];}).filter(function(b){return b&&b.type===kind;});h+='<div><div class="ms-section-head"><h4>'+ (kind==='industry'?'行业':'题材')+' <span class="ms-muted">'+rows.length+' 个强势方向</span></h4><button class="ms-detail-link" onclick="MS_VIEW.'+kind+'.scope=\''+axis+'\';MS_VIEW.'+kind+'.sort=\''+axis+'\';RENDERED.'+(kind==='industry'?'boards':'themes')+'=false;goPane(\''+(kind==='industry'?'boards':'themes')+'\')">全部 →</button></div><div class="ms-direction-grid">'+rows.slice(0,4).map(function(b){return msDirectionCard(b,axis);}).join('')+'</div>'+(!rows.length?'<p class="ms-muted">当前没有达到强势范围的方向。</p>':'')+'</div>';});h+='</div></section>';});
 host.innerHTML=h+'<p class="ms-muted">'+esc(meta.version||'')+' · '+esc(DATA.ui_generation||'')+' · 行业题材采用同花顺确认成员，最新源时间单独显示。</p>';
}
function renderWorkboard(){renderOverview();}

function msDetail(m){var ev=m.display_evidence||{},h='<section class="card market-strength-detail"><div class="ms-axis">'+msBadge(m,'trend')+msBadge(m,'emotion')+'</div><div class="ms-tag-list">'+msTags(m)+'</div><p>'+esc((m.background||{}).label||'')+' · '+esc(ev.structure||'')+'</p><p>'+esc((m.reasons||[]).join('；')||'—')+'</p><p class="ms-muted">距阶段高点 '+fmt(ev.drawdown_atr,2)+' ATR · '+[5,10,20].map(function(n){return '距MA'+n+' '+pctHtml((ev.ma_distance_pct||{})[n],2);}).join(' / ')+'</p>'+(m.new_strong_axes||[]).map(function(x){return '<p class="ms-muted">'+(x.axis==='trend'?'趋势':'情绪')+'新进入强势：'+esc(x.basis)+' '+esc(x.from_at)+' → '+esc(x.to_at||'—')+'</p>';}).join('')+'<p class="ms-card-risk">'+esc((m.risks||[]).join('；')||'')+'</p>';
 h+='<details><summary>强度计算依据与实际数值</summary><p>趋势：75%完成日历史力度 + 25%当前窗口力度，乘连续结构系数形成周期基础分；5/10/20日择主导，再按当前回落与短周期冲突折减总分。力度内部60%绝对收益 + 40%同周期分位；绝对收益在参考尺度80%以内线性计分，以上递减增长。个股参考尺度8/12/20%，板块5/8/12%；20/60日背景另列。板块结构与当前回落取有效成员均值。个股情绪：60%当日进攻 + 20%保持 + 20%近5日活跃；保持为75%日内位置与开盘后推进 + 25%有效报价抽样过程，抽样不足时过程分中性50。近5日按1/2/3/4/5递增权重，并扣减近期下跌压力。板块情绪：40%成员整体进攻 + 35%情绪强股比例 + 25%成员保持中位数。≥65强，≥80很强；单一价格涨停的快照保持分50，报价抽样不代表封板时长。</p><div class="tw"><table><thead><tr><th>周期</th><th>完成日涨幅</th><th>当前窗口涨幅</th><th>历史力度</th><th>当前力度</th><th>结构系数</th><th>趋势分</th></tr></thead><tbody>';
 [5,10,20].forEach(function(n){var p=(m.trend_parts_by_period||{})[n]||{};h+='<tr><td>'+n+'日</td>'+['historical_R','R','historical_G','G','K','T'].map(function(k){return '<td>'+fmt(p[k],2)+'</td>';}).join('')+'</tr>';});
 h+='</tbody></table></div><p>'+esc(m.version||'')+' · '+esc(m.mode||'')+' · 截至 '+esc(m.trend_at||m.emotion_at||'—')+' · UI '+esc(DATA.ui_generation||'')+'</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(JSON.stringify(m,null,2))+'</pre></details><details><summary>数据来源与缺口</summary>'+esc((m.data_reasons||[]).join('；')||'当前计算数据完整')+'</details></section>';return h;
}
function msHistoryGaps(s){var o=s.chart_observation||{},days=o.suspension_days||[];return days.length?'<details class="ms-history-gaps"><summary>停牌标注 · '+days.length+'日</summary><p>'+days.map(function(d){return esc(d)+((o.verified_suspension_days||[]).indexOf(d)>=0?'（已核验）':'（推定）');}).join(' / ')+'</p><p class="ms-muted">缺失交易日按停牌处理，仅绘制有效成交日；无公告证据的日期属于规则推定。</p></details>':'';}
function msChartAcquisitionNote(s){var state=s.chart_data_state;return state?msTag(state.label,state.basis+' 采集时间 '+state.checked_at,'risk')+' ':'';}
function showStock(code,boardId){var s=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).filter(function(r){return r.code===code;})[0];if(!s)return;
 var sources=[s.chart_history,s.strength_history],bars=sources.find(function(items){return Array.isArray(items)&&items.length>=1&&items.every(function(b){return b&&['open','high','low','close'].every(function(k){return typeof b[k]==='number'&&isFinite(b[k])&&b[k]>0;})&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&b.low<=b.high;});})||[],hasOHLC=bars.length>=1,paused=!!(s.emotion_relay&&(s.emotion_relay.suspended_current||!s.emotion_relay.valid&&(s.emotion_relay.history||[]).some(function(b){return b.halted&&b.date===String(DATA.quote_capture_at||'').slice(0,10);})));MS_CHART=null;
 var h='<section class="card"><div class="ms-card-head"><div><h3>'+esc(s.name)+' <span class="cd">'+esc(code)+'</span></h3><p class="ms-muted">'+esc(s.industry||s.industry_detail||'')+'</p></div><div class="detail-price">'+fmt(paused?((s.emotion_relay||{}).price||s.last_completed_close||s.price):s.price,2)+' <small>'+(paused?'停牌参考':pctHtml(s.change_pct,2))+'</small></div></div><h3>60日历史K线</h3>'+(hasOHLC?'<canvas id="k-cv" class="chart detail-chart" style="height:310px"></canvas><p class="ms-muted">'+(paused?msChartAcquisitionNote(s)+'停牌中 · 保留停牌前历史K线；复牌后继续绘制。':msChartAcquisitionNote(s)+(s.chart_source?(s.chart_source==='completed_daily_history'?(bars[0].price_basis==='qfq'?'前复权日K':'原价日K'):'日K')+' · MA5 / MA10 / MA20 · 成交量 · 截至 '+esc(s.chart_at||bars[bars.length-1].date):'完成日OHLC · MA5 / MA10 / MA20 · 成交量；现价仅在口径确认后画虚线，不补成完成日K线。'))+'</p>':'<p class="ms-muted">'+(paused?'停牌中 · 复牌后继续显示K线':msChartAcquisitionNote(s)+'日K线OHLC数据不足，待补齐')+'</p>')+msHistoryGaps(s)+'</section>'+msDetail(s.market_strength||{});
 var themes=s.themes||s.concepts||[];if(!Array.isArray(themes))themes=[themes];h+='<section class="card"><h3>个股概念归属</h3><p>'+esc(themes.map(function(t){return typeof t==='string'?t:t.name||'';}).join(' / ')||s.industry||'—')+'</p></section>';
 var confirmed=msBoardCatalog().filter(function(b){return (b.member_codes||[]).indexOf(code)>=0;});if(confirmed.length)h+='<section class="card"><h3>确认成员关系</h3><div class="ms-axis">'+confirmed.map(function(b){return '<button class="btn" onclick="pickBoardMembers(\''+jsq(b.id)+'\')">'+esc(b.name)+'</button>';}).join('')+'</div></section>'; openDrawer(esc(s.name)+' '+esc(code),'个股研究 · 历史结构与实时进攻',h,true);
 setTimeout(function(){var cv=document.getElementById('k-cv');if(cv){if(hasOHLC){var price=s.chart_source!=='completed_daily_history'&&(s.market_strength||{}).quote_at&&(s.market_strength||{}).price_context&&s.market_strength.price_context.valid?s.price:null;var gaps=(s.chart_observation||{}).suspension_days||[];bars=bars.map(function(b,i){return Object.assign({},b,{suspension_before:gaps.filter(function(d){return i>0&&d>bars[i-1].date&&d<b.date;})});});MS_CHART={bars:bars,price:price};var tools=document.createElement('div');tools.className='ms-chart-tools';tools.innerHTML='<label>显示区间 <select aria-label="K线显示区间" onchange="msChartRange(Number(this.value))"><option value="60">60日</option><option value="40">40日</option><option value="20">20日</option></select></label><span id="k-readout">移到K线上查看日期、OHLC与成交量</span>';cv.parentNode.insertBefore(tools,cv);msDrawCandles(cv,bars,price,60);}}},30);
}
var MS_CHART=null;
function msChartRange(n){var cv=document.getElementById('k-cv');if(cv&&MS_CHART)msDrawCandles(cv,MS_CHART.bars,MS_CHART.price,n);}
function msDrawCandles(cv,fullBars,price,count){var allMA=[5,10,20].map(function(n){return ma(fullBars.map(function(b){return b.close;}),n);}),bars=fullBars.slice(-(count||60)),mas=allMA.map(function(a){return a.slice(-bars.length);});var dpr=window.devicePixelRatio||1,w=cv.clientWidth||600,h=cv.clientHeight||310,g=cv.getContext('2d');cv.width=w*dpr;cv.height=h*dpr;g.scale(dpr,dpr);g.clearRect(0,0,w,h);
 var pad=45,top=22,bottom=h*.73,volTop=h*.79,step=(w-pad-15)/bars.length,values=[];
 bars.forEach(function(b){values.push(b.high,b.low);});if(price>0)values.push(price);var lo=Math.min.apply(null,values),hi=Math.max.apply(null,values),range=hi-lo||1;lo-=range*.04;hi+=range*.04;
 var x=function(i){return pad+(i+.5)*step;},y=function(v){return bottom-(v-lo)/(hi-lo)*(bottom-top);};g.font='10px sans-serif';g.fillStyle='#8b929d';
 for(var j=0;j<4;j++){var v=lo+(hi-lo)*j/3,yy=y(v);g.strokeStyle='#eceef2';g.beginPath();g.moveTo(pad,yy);g.lineTo(w-15,yy);g.stroke();g.fillText(v.toFixed(2),2,yy+3);}
 var maxVol=Math.max.apply(null,bars.map(function(b){return b.volume||0;}))||1;
 bars.forEach(function(b,i){var color=b.close>=b.open?'#dc403e':'#15966c',xx=x(i),body=Math.max(1,step*.58);g.strokeStyle=color;g.beginPath();g.moveTo(xx,y(b.high));g.lineTo(xx,y(b.low));g.stroke();g.fillStyle=color;g.fillRect(xx-body/2,Math.min(y(b.open),y(b.close)),body,Math.max(1,Math.abs(y(b.open)-y(b.close))));var vh=(b.volume||0)/maxVol*(h-volTop-20);g.fillRect(xx-body/2,h-20-vh,body,vh);});
 ['#e19a2d','#8a6bb1','#367ad6'].forEach(function(color,i){g.strokeStyle=color;g.lineWidth=1.2;g.beginPath();var started=false;mas[i].forEach(function(v,j){if(v==null)return;if(!started){g.moveTo(x(j),y(v));started=true;}else g.lineTo(x(j),y(v));});g.stroke();g.fillStyle=color;g.fillText('MA'+[5,10,20][i],pad+i*65,12);});
 if(price>0){g.setLineDash([4,4]);g.strokeStyle='#768294';g.beginPath();g.moveTo(pad,y(price));g.lineTo(w-15,y(price));g.stroke();g.setLineDash([]);g.fillStyle='#768294';g.fillText('现价 '+fmt(price,2),w-105,12);}
 g.fillStyle='#8b929d';g.fillText(bars[0].date,pad,h-3);g.fillText(bars[bars.length-1].date,w-85,h-3);g.fillText('成交量（万股）',pad,volTop-3);g.fillText(volumeWan(maxVol),pad,volTop+10);bars.forEach(function(b,i){if((b.suspension_before||[]).length){g.fillStyle='#687f9d';g.fillText('停',x(i)-4,top+9);}});
 cv.onpointermove=function(e){var rect=cv.getBoundingClientRect(),i=Math.max(0,Math.min(bars.length-1,Math.floor((e.clientX-rect.left-pad)/step))),b=bars[i],out=document.getElementById('k-readout');if(out)out.textContent=b.date+' · 开 '+fmt(b.open,2)+' 高 '+fmt(b.high,2)+' 低 '+fmt(b.low,2)+' 收 '+fmt(b.close,2)+' · 成交量 '+volumeWan(b.volume)+((b.suspension_before||[]).length?' · 前段停牌（推定） '+b.suspension_before.join(' / '):'');};
}
function showBoardById(id){var b=boardById(id);if(!b)return;var members=b.members||[],idx=(b.market_strength||{}).index_reference||{};var html=msDetail(b.market_strength||{})+'<section class="card"><h3>官方指数参照</h3><p>'+esc(idx.source||'同花顺指数')+' · '+pctHtml(idx.change_pct==null?idx.ret1:idx.change_pct,2)+' · '+esc(idx.quote_at||idx.asof||'—')+'</p><p class="ms-muted">成员共振与官方指数分别计算。</p></section><section class="card"><h3>同花顺确认主板成员 · '+members.length+'只</h3><button class="btn" onclick="pickBoardMembers(\''+jsq(id)+'\')">在个股页查看该板块全部成员</button>'+msTable(members,'members')+'</section>';openDrawer(esc(b.name),'板块研究 · 成员共振与指数参照',html,true);}
function resetMSMemberView(){STATE.q='';var input=document.getElementById('q');if(input)input.value='';STATE.boardFilterId=null;MS_VIEW.stocks=msStockDefaults();}
function pickBoardMembers(id){if(!boardById(id))return toast('板块成员暂无数据');msOpenStocks(id,'trend',true);}
function clearMSMembers(){resetMSMemberView();MS_VIEW.stocks.scope='all';renderStocks();}
function boardMemberRows(b,codes){return msTable((b.members||[]).filter(function(r){return codes.indexOf(r.code)>=0;}),'members');}
function downloadMSCSV(text,name){if(text.charAt(0)!=='\ufeff')text='\ufeff'+text;var blob=new Blob([text],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(function(){URL.revokeObjectURL(a.href);},1000);}
function msCSV(key){if(key==='radar')return mtCSV();if(key==='stocks'&&DATA.stock_board_ranking)return msRankCSV();var rows=msRows(key);if(key==='industry'||key==='theme'){var generation=DATA.ui_generation,name='板块强度_'+key+'_'+generation+'.csv';if(DATA.ui_lazy){return fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:generation,kind:'board',ids:rows.map(function(r){return r.id;})})}).then(function(r){if(!r.ok)throw new Error('导出失败 '+r.status);return r.text();}).then(function(text){downloadMSCSV(text,name);}).catch(function(e){toast(e.message);throw e;});}var headers=['ID','名称','趋势分','情绪分','主导周期','阶段','版本','UI版本','完整模型依据'];function cell(v){return v==null?'':'"'+String(v).replace(/"/g,'""')+'"';}downloadMSCSV('\ufeff'+[headers.join(',')].concat(rows.map(function(r){var m=r.market_strength;return [r.id,r.name,m.trend_score,m.emotion_score,m.dominant_period,m.phase,m.version,generation,JSON.stringify(m)].map(cell).join(',');})).join('\n'),name);return;}return exportCSV(rows,'强势研究_'+DATA.ui_generation+'.csv');}
function radarOpportunityDetail(s){return msDetail(s.market_strength||{});}
var legacyExportCSV=typeof exportCSV==='function'?exportCSV:function(){};exportCSV=function(rows,name){return legacyExportCSV(Array.isArray(rows)?rows:msRows('stocks'),name||'强势研究_'+DATA.ui_generation+'.csv');};


// Only the overview's board projection changes; stock judgments and stored data stay intact.
document.addEventListener('DOMContentLoaded',function(){
 if(typeof mtModel==='function'){
  var baseMtModel=mtModel;
  mtModel=function(){var m=baseMtModel();return m?Object.assign({},m,{boards:(m.boards||[]).filter(function(b){return msOfficialBoard(boardById(b.id));})}):m;};
  if(typeof renderOverview==='function')renderOverview();
 }
},{once:true});
