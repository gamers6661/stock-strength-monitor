/* Loaded after all page renderers: every auction view reads the same backend judgment. */
(function(){
 function today(){var d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
 function active(){return sessionNow()==='竞价结束'&&String(DATA.quote_capture_at||'').slice(0,10)===today();}
 function model(){return DATA.session_context||{};}
 function rows(){return model().auction_rows||[];}
 function stamp(){var m=model(),at=(DATA.intraday_model||{}).auction_latest_quote_at;return '竞价价格判断 · 源报价 '+(at||'待更新')+' · 价格判断 '+(m.price_judged_count||0)+'只 · 结构可核验 '+(m.structure_judged_count||0)+'只';}
 function notice(){return '<p class="ms-muted">'+esc(stamp())+'。采用最新有效竞价价格判断承接、突破与均线风险。</p>';}
 function stockMap(){var map={};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(r){map[r.code]=r;});return map;}
 function judgment(c){return '<div class="ms-tag-list">'+msTag(c.current_label||c.label,c.reason,c.risks&&c.risks.length?'risk':'')+'</div><span class="cd">'+esc(c.quote_at||'报价待更新')+'</span>';}
 function table(items,limit){var shown=limit?items.slice(0,limit):items,map=stockMap();return '<div class="tw"><table class="market-strength-table aq-stock-table"><thead><tr><th class="l">股票</th><th>竞价价格 / 涨幅</th><th>价格进攻</th><th class="l">最新价格判断</th><th class="l">风险 / 背景</th></tr></thead><tbody>'+shown.map(function(c){var s=map[c.code]||{};return '<tr data-auction-code="'+esc(c.code)+'" class="clickable" onclick="showStock(\''+jsq(c.code)+'\')"><td class="l"><b>'+esc(c.name||c.code)+'</b><span class="cd">'+esc(c.code)+'</span>'+msAffiliation(s,'stocks')+'</td><td>'+fmt(c.price,2)+'<span class="cd">'+pctHtml(c.gap_pct,2)+'</span></td><td>'+(c.price_attack_score==null?'—':fmt(c.price_attack_score,1)+' · '+esc(c.price_attack_tier||''))+'</td><td class="l">'+judgment(c)+'</td><td class="l">'+esc((c.risks||[]).join('；')||(c.price_basis_valid?'当前未触发价格风险':c.reason||'口径待核验'))+'<span class="cd">昨日 '+esc(c.prior_daily_tier||'待评分')+'档'+(c.previous_close_board?' · 真实收盘主榜':'')+'</span></td></tr>';}).join('')+'</tbody></table></div>'+(!items.length?'<p class="empty">本轮尚无有效竞价判断。</p>':'');}
 function boardRows(kind){var source=msBoardCatalog();return source.filter(function(b){return !kind||b.type===kind;}).slice().sort(function(a,b){var av=a.member_auction||{},bv=b.member_auction||{};return Number(bv.ready)-Number(av.ready)||(bv.change_pct==null?-Infinity:bv.change_pct)-(av.change_pct==null?-Infinity:av.change_pct);});}
 function boardTable(boards,limit){return '<div class="tw"><table class="market-strength-table aq-board-table"><thead><tr><th class="l">方向</th><th>主板成员竞价等权</th><th>上涨占比</th><th>有效覆盖</th><th>源报价</th></tr></thead><tbody>'+boards.slice(0,limit||boards.length).map(function(b){var a=b.member_auction||{};return '<tr data-auction-board="'+esc(b.id)+'"><td class="l"><button class="ms-name-link" onclick="showBoardById(\''+jsq(b.id)+'\')">'+esc(b.name)+'</button><span class="cd">'+(b.type==='industry'?'行业':'题材')+'</span></td><td>'+pctHtml(a.ready?a.change_pct:null,2)+'</td><td>'+fmt(a.ready?a.up_pct:null,1)+'%</td><td>'+(a.valid_count||0)+' / '+(a.pool_count||0)+'<span class="cd">'+fmt(a.coverage_pct,1)+'%</span></td><td>'+esc(a.quote_at||'待更新')+'</td></tr>';}).join('')+'</tbody></table></div><p class="ms-muted">当前有效主板成员等权；不足6只保留覆盖信息。官方指数在详情单列。</p>';}
 var query='',scope='all',limit=100;
 function selected(key){var v=MS_VIEW[key]||{},q=query||v.q||'',map=stockMap();return rows().filter(function(c){var s=map[c.code]||c;return (!q||String(c.code+' '+c.name).indexOf(q)>=0)&&(!scope||scope==='all'||scope==='focus'&&c.monitor_candidate||scope==='risk'&&(c.risks||[]).length)&&(!v.industryIds||msMatchDirections(s,key));});}
 window.aqSet=function(field,value,key){if(field==='query')query=value;if(field==='scope')scope=value;if(field==='limit')limit+=100;draw(key);};
 function tools(key){return '<div class="ms-toolbar"><select aria-label="竞价筛选" onchange="aqSet(\'scope\',this.value,\''+key+'\')">'+[['all','全部竞价判断'],['focus','转强与承接观察'],['risk','失守与风险观察']].map(function(o){return '<option value="'+o[0]+'" '+(scope===o[0]?'selected':'')+'>'+o[1]+'</option>';}).join('')+'</select><input aria-label="竞价搜索" placeholder="代码 / 名称" value="'+esc(query)+'" onchange="aqSet(\'query\',this.value,\''+key+'\')"></div>';}
 function draw(key){var id=key==='radar'?'ma-radar-host':key==='emotion'?'emotion-host':'ms-stock-host',host=document.getElementById(id);if(!host)return;
  var items=selected(key);host.innerHTML=notice()+(key==='stocks'?msDirectionPicker():'')+tools(key)+'<p class="ms-muted">当前 '+items.length+' 只；同一份竞价价格、结构判断与源时间。</p>'+table(items,limit)+(items.length>limit?'<button class="btn" onclick="aqSet(\'limit\',null,\''+key+'\')">加载更多</button>':'');}
 var oldRender=msRender,oldRows=msRows;
 var oldTable=msTable;
 msTable=function(items,key,count){if(active()&&key==='members'){var codes={};items.forEach(function(r){codes[r.code]=true;});return table(rows().filter(function(c){return codes[c.code];}),count);}return oldTable(items,key,count);};
 msRows=function(key,axis){if(active()&&key==='stocks'){var map=stockMap();return selected(key).map(function(c){return map[c.code];}).filter(Boolean);}return oldRows(key,axis);};
 msRender=function(key){if(!active())return oldRender(key);if(key==='industry'||key==='theme')return drawBoards(key);draw(key);};
 var oldStocks=renderStocks;
 renderStocks=function(){oldStocks();if(active()){document.getElementById('stk-sub').textContent=stamp();draw('stocks');}};
 function drawBoards(kind){var host=document.getElementById(kind==='theme'?'theme-center':'board-center');if(host)host.innerHTML=notice()+boardTable(boardRows(kind==='industry'?null:kind));var metric=document.getElementById('bd-metrics');if(metric)metric.innerHTML='';}
 var oldBoards=renderBoards,oldThemes=renderThemesPage,oldRadar=mtRender,oldEmotion=renderEmotion;
 renderBoards=function(){return active()?drawBoards('industry'):oldBoards();};
 renderThemesPage=function(){return active()?drawBoards('theme'):oldThemes();};
 mtRender=function(){return active()?draw('radar'):oldRadar();};
 renderEmotion=function(){if(active()){var sub=document.getElementById('emotion-sub');if(sub)sub.textContent=stamp();draw('emotion');return;}return oldEmotion();};
 var oldOverview=renderOverview;
 renderOverview=function(){oldOverview();var host=document.getElementById('ms-overview-host');if(!host)return;
  if(active()){document.getElementById('hero-h1').textContent='竞价价格与结构观察';document.getElementById('hero-p').textContent='最新竞价价格 · 昨日结构 · 承接与失守风险';document.getElementById('hero-stamp').textContent=stamp();
   var focused=rows().filter(function(c){return c.monitor_candidate;}),risks=rows().filter(function(c){return (c.risks||[]).length;});
   host.innerHTML='<section class="card aq-overview">'+notice()+'<p>转强与承接观察 '+focused.length+' 只 · 失守与风险 '+risks.length+' 只</p>'+boardTable(boardRows(),12)+'<h3>竞价转强与承接</h3>'+table(focused,20)+'<h3>竞价失守与风险</h3>'+table(risks,12)+'</section>';}
 };
 var oldStock=showStock,oldBoard=showBoardById;
 function stockDetail(c,title){return '<section class="card aq-judgment"><h3>'+title+'</h3><p>¥'+fmt(c.price,2)+' · '+pctHtml(c.gap_pct,2)+' · 源报价 '+esc(c.quote_at)+'</p>'+judgment(c)+'<p>价格进攻 '+fmt(c.price_attack_score,1)+' · MA10 '+fmt(c.current_ma10,3)+' · MA20 '+fmt(c.current_ma20,3)+'</p><p>'+esc((c.risks||[]).join('；')||c.reason)+'</p></section>';}
 showStock=function(code,boardId){var result=oldStock(code,boardId),s=stockMap()[code],host=document.getElementById('dr-b');if(!s||!host)return result;var c=active()?s.session_context:null;
  if(c&&c.quote_valid){host.insertAdjacentHTML('afterbegin',stockDetail(c,'最新竞价判断'));if(active()){var price=host.querySelector('.detail-price');if(price)price.innerHTML=fmt(c.price,2)+' <small>'+pctHtml(c.gap_pct,2)+'</small>';}}return result;};
 showBoardById=function(id){var result=oldBoard(id);if(!active())return result;var b=boardRows().find(function(x){return x.id===id;}),host=document.getElementById('dr-b');if(b&&host)host.insertAdjacentHTML('afterbegin','<section class="card aq-board-detail"><h3>'+'最新竞价成员判断'+'</h3>'+boardTable([b])+'</section>');return result;};
})();
