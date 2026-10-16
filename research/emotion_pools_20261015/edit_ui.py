from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'emotion_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("r&&msMatchDirections(r,'emotion')&&",'r&&')
s=s.replace("if(key==='emotion')return renderEmotion();","if(['emotion','emotionCaps','emotionBreaks'].indexOf(key)>=0)return renderEmotion();")
lines=s.splitlines()
for i,line in enumerate(lines):
    if "h+='<section" in line and '分板位晋级与负反馈' in line:
        lines[i]=" h+=erPromotionSection(meta);h+=erCapSection(meta);h+=erBreakSection(meta);"
    if "h+='<section" in line and '龙头与接续观察' in line:
        lines[i]=line.replace("+msDirectionPicker('emotion')+",'+').replace(
            ",['sealed','当前在板'],['broken','断板反馈']",'')
    if 'erPut(host,h,focus,' in line and '情绪股票搜索' in line:
        lines[i]=line.replace("['情绪股票搜索','搜索板块题材']","['情绪股票搜索','涨停池股票搜索','断板池股票搜索']")
    if 'var ER_OLD_BOARD=' in line:
        start=line.index('<button class="btn" onclick="MS_VIEW.emotion.themeIds')
        end=line.index('</button>',start)+len('</button>')
        lines[i]=line[:start]+'''<button class="btn" onclick="pickBoardMembers(\\''+jsq(id)+'\\')">查看完整成员接力排名</button>'''+line[end:]
s='\n'.join(lines)+'\n'
new=r'''
// Dedicated pools keep their own search state and use backend membership/order.
function erByCodes(codes,key){
 var by={},v=MS_VIEW[key]||{};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(r){by[r.code]=r;});
 return (codes||[]).map(function(c){return by[c];}).filter(function(r){return r&&erFresh(r.emotion_relay)&&(!v.q||(r.code+' '+r.name).indexOf(v.q)>=0);});
}
function erCapRows(){var v=MS_VIEW.emotionCaps,meta=erModel(),pool=meta.pools||{},ids=v.height==='all'?meta.lists.sealed:(pool.groups||{})[v.height];return erByCodes(ids,'emotionCaps');}
function erBreakRows(){return erByCodes(erModel().lists.broken,'emotionBreaks');}
function erPoolSearch(key,label){return '<input aria-label="'+label+'" placeholder="代码 / 名称" value="'+esc(MS_VIEW[key].q)+'" data-ms-search-key="'+key+'" data-ms-search-field="q" oninput="msSearchInput(event,this,\''+key+'\',\'q\')">';}
function erPoolCSV(kind){return msExportRows(kind==='sealed'?erCapRows():erBreakRows(),'emotion',(kind==='sealed'?'当日涨停池_':'高标断板池_')+DATA.ui_generation+'.csv');}
function erCapTable(rows){
 var h='<div class="tw"><table class="market-strength-table er-cap-table"><thead><tr><th class="l">个股 / 板位</th><th>同板位强度序</th><th class="l">封板状态</th><th>封单 / 成交额</th><th>首次 / 最后封板</th><th>炸板次数</th><th>今日涨幅 / 换手</th></tr></thead><tbody>';
 rows.forEach(function(r){var m=r.emotion_relay,s=m.cap_strength||{},ok=s.verified,tags=ok?(s.labels||[]):['封板明细待核验'];
  h+='<tr data-cap-code="'+r.code+'" class="clickable" onclick="showStock(\''+jsq(r.code)+'\')"><td class="l"><b>'+esc(r.name)+'</b><span class="cd">'+r.code+'</span><b class="er-position">'+esc(erHeight(m))+'</b></td><td>'+(ok?'<b class="er-pool-rank">'+(m.height_exact?s.height_rank:'—')+'</b><span class="cd">'+(m.height_exact?m.height+'板内比较':'连板链待核验')+'</span>':'<span class="ms-muted">明细待补齐</span>')+'</td><td class="l"><div class="ms-tag-list">'+tags.concat((m.risks||[]).filter(function(x){return x.indexOf('一字')>=0;})).map(function(t){return msTag(t,s.reason||'涨停池统计源时间 '+s.source_at,'er-tag');}).join('')+'</div><span class="cd">'+esc(s.source_at||s.reason||'')+'</span></td><td>'+(ok?'<b>'+fmt(s.seal_to_amount_pct,2)+'%</b><span class="cd">封单 '+fmt(s.seal_amount_yuan/10000,0)+'万<br>成交 '+fmt(s.amount_yuan/10000,0)+'万</span>':'—')+'</td><td>'+(ok?esc(s.first_seal)+'<span class="cd">最后 '+esc(s.last_seal)+'</span>':'—')+'</td><td>'+(ok?s.reopen_count+'次':'—')+'</td><td>'+pctHtml(m.feedback_pct,2)+'<span class="cd">换手 '+fmt(m.turnover_pct,2)+'%</span></td></tr>';
 });return h+'</tbody></table></div>';
}
function erCapSection(meta){
 var p=meta.pools||{},v=MS_VIEW.emotionCaps,rows=erCapRows(),opts=[['all','全部板数 · '+meta.lists.sealed.length+'只']];
 Object.keys(p.groups||{}).forEach(function(k){opts.push([k,(k==='unknown'?'连板链待核验':k+'板')+' · '+p.groups[k].length+'只']);});
 return '<section class="card er-pool" id="er-cap-pool"><div class="er-section-heading"><div><span class="er-eyebrow">LIMIT UP · '+esc(meta.mode)+'</span><h3>当日涨停池 <small>'+meta.lists.sealed.length+'只</small></h3></div><span>板数优先，同板数比较封板强度</span></div><div class="ms-toolbar">'+msSelect('height',opts,'emotionCaps','涨停池板数')+erPoolSearch('emotionCaps','涨停池股票搜索')+'<button class="btn" onclick="erPoolCSV(\'sealed\')">导出涨停池</button></div><p class="ms-muted">'+esc(p.strength_basis||'')+' 强度明细 '+(p.strength_coverage||0)+'/'+(p.strength_expected||0)+'只；统计源 '+esc(p.source_at||'待更新')+'。'+(meta.mode==='正式收盘'?'仅含当日核验收盘封板股。':'仅含最新有效报价仍在板的股票，待收盘确认。')+'一字板另标成交受限。</p>'+erCapTable(rows.slice(0,v.limit))+msMore(rows,rows.slice(0,v.limit),'emotionCaps')+'</section>';
}
function erBreakTable(rows){
 var h='<div class="tw"><table class="market-strength-table er-break-table"><thead><tr><th class="l">个股 / 原高度</th><th class="l">断板事件</th><th class="l">最新反馈</th><th>今日涨幅</th><th>断板后累计 / 距末板</th><th>断板日低 / 高</th></tr></thead><tbody>';
 rows.forEach(function(r){var m=r.emotion_relay,b=m.break_watch||{},tags=[b.pending?'盘中分歧·待收盘':'正式收盘断板'];if(b.was_market_highest)tags.push('断板前市场最高标');
  h+='<tr data-break-code="'+r.code+'" class="clickable" onclick="showStock(\''+jsq(r.code)+'\')"><td class="l"><b>'+esc(r.name)+'</b><span class="cd">'+r.code+'</span><b class="er-position">原'+b.height+'板</b></td><td class="l"><b>'+esc(b.date)+'</b><span class="cd">'+(b.pending?'尚未确认断板':'断板后 '+b.sessions_since+' 个交易日')+'<br>末板 '+esc(b.last)+'</span><div class="ms-tag-list">'+tags.map(function(t){return msTag(t,'本轮 '+b.start+' — '+b.last,'er-tag');}).join('')+'</div></td><td class="l"><div class="ms-tag-list">'+(b.labels||[]).map(function(t){return msTag(t,'实际源时间 '+m.quote_at,t.indexOf('负反馈')>=0||t.indexOf('跌破')>=0?'risk':'er-tag');}).join('')+'</div><span class="cd">'+esc(m.quote_at)+'</span></td><td>'+pctHtml(m.feedback_pct,2)+'</td><td>'+pctHtml(b.since_break_pct,2)+'<span class="cd">距最后封板收盘 '+pctHtml(b.from_last_seal_pct,2)+'</span></td><td>'+fmt(b.break_low,2)+' / '+fmt(b.break_high,2)+'<span class="cd">断板日涨幅 '+pctHtml(b.break_return_pct,2)+'</span></td></tr>';
 });return h+'</tbody></table></div>';
}
function erBreakSection(meta){var rows=erBreakRows(),v=MS_VIEW.emotionBreaks,p=meta.pools||{};return '<section class="card er-pool" id="er-break-pool"><div class="er-section-heading"><div><span class="er-eyebrow">BROKEN CHAIN · FOLLOW THROUGH</span><h3>断板观察池 <small>'+meta.lists.broken.length+'只</small></h3></div><span>原高度至少3板 · 跟踪后续反馈</span></div><div class="ms-toolbar">'+erPoolSearch('emotionBreaks','断板池股票搜索')+'<button class="btn" onclick="erPoolCSV(\'broken\')">导出断板池</button></div><p class="ms-muted">观察最近20个交易日中最后一轮≥3板的断板；盘中分歧待收盘，停牌不算断板，再次封板后结束旧断板观察。先看断板前地位，再看修复、持续回落及真实跌停等反馈，不凭单日反弹确认龙头。最新报价待核验 '+(p.broken_pending||[]).length+'只，不混入有效反馈。累计按断板日收盘计算。</p>'+erBreakTable(rows.slice(0,v.limit))+msMore(rows,rows.slice(0,v.limit),'emotionBreaks')+'</section>';}
function erPromotionSection(meta){return '<section class="card"><div class="er-section-heading"><h3>分板位晋级与负反馈</h3><span>有效分母与缺口分别显示 · 点击查看晋级名单</span></div><div class="er-promotion">'+(meta.promotion||[]).map(function(p){return '<button class="er-promotion-card" data-promotion-height="'+p.height+'" onclick="erOpenPromotion('+p.height+')" aria-label="查看'+p.height+'进'+(p.height+1)+'板晋级名单"><b>'+p.height+'→'+(p.height+1)+'板</b><strong>'+fmt(p.promotion_pct,1)+'%</strong><small>'+p.sealed+'/'+p.valid+'有效 · 应跟踪 '+p.expected+' · 中位 '+pctHtml(p.median_return_pct,2)+'</small><span class="er-promotion-link">查看 '+p.sealed+' 只'+(meta.mode==='正式收盘'?'晋级成功':'在板待确认')+' →</span></button>';}).join('')+'</div><p class="ms-muted">昨日断板队列 '+meta.broken_feedback.expected+'只 · 今日有效 '+meta.broken_feedback.valid+'只 · 中位反馈 '+pctHtml(meta.broken_feedback.median_return_pct,2)+' · 明显负反馈 '+meta.broken_feedback.large_loss_count+'只。≥3板断板的连续后续观察见下方独立名单。</p></section>';}
function erPromotionRows(height){var p=(erModel().promotion||[]).find(function(x){return x.height===height;});return erByCodes(p?p.success_codes:[],'promotion');}
function erOpenPromotion(height){var meta=erModel(),p=meta.promotion.find(function(x){return x.height===height;}),rows=erPromotionRows(height);if(!p)return;openDrawer(height+'→'+(height+1)+'板 · '+(meta.mode==='正式收盘'?'晋级成功':'在板待确认'),esc(meta.mode+' · '+meta.source_at),'<p class="ms-muted">前一完成日 '+esc(meta.prior_history_asof)+' 为'+height+'板的队列，共 '+p.expected+'只；今日有效 '+p.valid+'只，'+p.sealed+'只'+(meta.mode==='正式收盘'?'收盘晋级成功':'当前在板，待收盘确认')+'；待核验 '+p.pending_codes.length+'只不计失败。有效名单 '+rows.length+'只。</p><button class="btn" onclick="erPromotionCSV('+height+')">导出晋级名单</button><div id="er-promotion-list">'+(rows.length?erTable(rows):'<p class="empty">当前没有可展示的有效晋级名单。</p>')+'</div>',true);}
function erPromotionCSV(height){return msExportRows(erPromotionRows(height),'emotion',height+'进'+(height+1)+'板晋级_'+DATA.ui_generation+'.csv');}
function erPoolDetail(m){var s=m.cap_strength,b=m.break_watch,h='';if(s)h+='<h4>同板位封板强度</h4><p>'+esc(s.verified?'炸板 '+s.reopen_count+'次；首次 '+s.first_seal+'，最后 '+s.last_seal+'；封单/成交额 '+fmt(s.seal_to_amount_pct,2)+'%。':s.reason)+'<span class="cd">'+esc(s.source+' · '+(s.source_at||'待核验'))+'</span></p>';if(b)h+='<h4>高标断板后续</h4><p>原'+b.height+'板，末板 '+esc(b.last)+'，'+esc(b.pending?'盘中分歧待确认':b.date+' 正式断板')+'。断板日区间 '+fmt(b.break_low,2)+' — '+fmt(b.break_high,2)+'；断板后累计 '+pctHtml(b.since_break_pct,2)+'。'+esc(b.basis)+'</p>';return h;}
'''
s=s.replace("+'<h4>异动与停复牌披露", "+erPoolDetail(m)+'<h4>异动与停复牌披露")
s+=new
p.write_text(s,encoding='utf-8')
p=root/'dashboard_template.html';s=p.read_text(encoding='utf-8')
s=s.replace('.er-promotion>div{','.er-promotion>button{')
css='''.er-pool{margin-top:24px}.er-pool h3 small{font-weight:500;font-size:12px;color:#8d929c;margin-left:8px}.er-pool .ms-toolbar{margin-bottom:14px}.er-pool .ms-toolbar input{background-image:none;padding-left:14px}.er-promotion-card{font:inherit;color:inherit;text-align:left;cursor:pointer;transition:border-color .15s,transform .15s}.er-promotion-card:hover{border-color:#b49b7d;transform:translateY(-2px)}.er-promotion-card:focus-visible{outline:2px solid #9c7853;outline-offset:3px}.er-promotion-link{font-size:11px;color:#8f745a}.er-cap-table{min-width:1000px}.er-break-table{min-width:1100px}.er-cap-table td,.er-break-table td{vertical-align:top;white-space:normal}.er-cap-table td:first-child,.er-break-table td:first-child{min-width:135px}.er-break-table td:nth-child(2),.er-break-table td:nth-child(3){min-width:195px;max-width:300px}.er-pool-rank{display:inline-flex;align-items:center;justify-content:center;background:#f4ede3;border:1px solid #e8dbc8;width:30px;height:30px;border-radius:10px;color:#896646;font-size:14px}.er-pool .ms-muted{line-height:1.9}.er-pool .cd{margin-top:7px;line-height:1.7}.er-pool .ms-tag-list{gap:6px;margin:6px 0}.er-pool .ms-tag{font-size:10px;padding:4px 8px;border-radius:6px}@media(max-width:650px){.er-pool .er-section-heading{flex-direction:column;align-items:flex-start}.er-pool .ms-toolbar{flex-wrap:wrap}.er-pool .ms-toolbar input{min-width:0;width:100%}.er-promotion>button{min-width:42%}}'''
s=s.replace('</style>',css+'\n</style>',1);p.write_text(s,encoding='utf-8')
p=root/'csv_export.js';s=p.read_text(encoding='utf-8');s=s.replace("'异动披露与参考','规则版本'","'异动披露与参考','封板强度依据','高标断板后续','规则版本'",1)
s=s.replace("JSON.stringify(m.regulation||{}),DATA.emotion_relay.version","JSON.stringify(m.regulation||{}),JSON.stringify(m.cap_strength||{}),JSON.stringify(m.break_watch||{}),DATA.emotion_relay.version",1);p.write_text(s,encoding='utf-8')
