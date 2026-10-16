/* Complete member ranks and shared explanations. Numeric ranks come from backend. */
var MS_EXPLANATIONS={
 '涨停重建均线后确认':'当前无有效阶段，旧波段已退出，或首次起涨前已完成日失守MA10。从MA5下方涨停收回MA5后，5个交易日内再次收盘涨停，站上已经转升的MA5及MA10，期间完成日守住MA5，才确认新波段。起涨事件日与实际确认日分开，不把首板回填为已入选。该入口至少包含两次封板，不要求首板时均线已转向。',
 '后续完成日涨停确认':'起涨事件之后又一个完成日收盘封住涨停，同时收复上行的MA5及MA10；起涨以来完成日没有失守MA5。与首板一起形成至少两次封板的强势证据。',
 '有效样本观察':'展示全部真实日线，能形成完整周期的均线正常计算；尚未凑足周期的指标留空，不补造历史或价格。',
 '停牌观察':'同批其他股票有当日成交，本股单独重试后仍未获取到当日成交，按缺失规则推定停牌，保留最后有效阶段，复牌后继续。',
 'MA10跟踪':'涨停收复候选以MA10为防守位继续观察，尚未确认正式均线趋势。连续15个交易分钟未收回、正式收盘失守或明显破位时失效；午休不计时。',
 '涨停收复':'旧波段已经结束，完成日收盘封住涨停，重新站上MA5及MA10且两线向上，前一日曾低于至少一条线。独立的新启动候选事件，不要求突破前20日高点，量比单独展示，不直接算作合格趋势。仅展示最新一轮、含当前交易日在内最近5个交易日仍有效的候选；MA10失守、正式确认、过期及数据待核验时隐藏标签。',
 '涨停收复·新启动候选':'完成日涨停收复已成立，继续跟踪候选MA10；等待后续完成日沿MA5继续上涨确认，或通过原有独立强势入口；当前不计入三阶段有效观察。',
 '候选已失效':'涨停收复候选的MA10有效失守；保留事件日期和失效依据供回看。',
 '阶段待确认':'已出现独立候选事件，但尚未通过MA5/MA10/MA20正式阶段准入。',
 'MA20整理跟踪':'本轮上涨已达到20%及4 ATR，失守MA10但仍守住MA20，先继续跟踪；尚未回踩MA20或形成合格平台，不计入有效近线观察。',
 '再启动待确认':'MA10或MA20整理后已重新站上MA5，等待后续完成日继续上涨、超过观察日收盘且MA5及MA10上行。确认后进入原阶段的推进状态，阶段标签不切回MA5。',
 '涨停收复后推进确认':'近5个交易日的有效涨停收复后，至少一个完成日收盘高于前日和收复日、守住MA5且MA5及MA10上行，期间MA10未失守。收复日记为本轮起点，后续确认日单独记录。',
 '涨停起涨后强势确认':'旧波段结束后出现涨停收复MA5，但当时未通过正式入口。后续5日内通过原有强势入口且两线向上，才关联该次起涨日；不会回填起涨日已入选。',
 'MA20整理后再启动':'同一轮趋势的MA20阶段收复MA5，后续完成日继续上涨、超过观察日收盘且MA5及MA10上行，进入MA20阶段内的推进状态。保留MA20阶段和整轮原始启动日，另记再启动观察日和确认日；推进不等于近线推荐。',
 'MA10承接后再启动':'同一轮趋势的MA10阶段收复MA5，后续完成日继续上涨、超过观察日收盘且MA5及MA10上行，进入MA10阶段内的推进状态。原阶段和整轮启动日不变。',
 '本轮启动':'本轮首次有效强势事件的日期。阶段降级和同轮再启动均不改写；整轮支撑失效退出后，才允许建立新一轮启动。',
 '阶段进入':'进入当前MA5、MA10或MA20阶段的确认日期。阶段转换不等于整轮趋势结束。',
 '再启动观察':'同轮MA10或MA20整理后重新站上MA5并上涨的观察事件，等待后续完成日继续推进确认。',
 '再启动确认':'后续完成日高于前日和观察日收盘，守住MA5及MA10且两线向上。进入原MA10或MA20阶段内的推进状态，阶段标签与原始启动日期保留。',
 '前段上涨不足':'已经从同轮MA5转入MA10跟踪，但本上涨段尚未达到10%且3 ATR的正式观察门槛；继续以MA10防守，不因MA5失守直接结束整轮趋势。',
 'MA5初期推进':'本轮首次通过完成日放量上攻、有效突破、涨停突破或涨停收复后确认，随后沿MA5推进。已进入MA10/MA20的股票收复MA5，显示原阶段内的推进状态。确认失守MA5转入MA10承接，不直接退出。',
 'MA10承接整理':'同轮MA5推进后失守MA5，转入MA10承接；前段上涨至少10%且3 ATR才属于正式观察，未达标保留承接跟踪。本轮强势推进失守MA5后转入MA10承接。承接观察与紧缩整理平台分别说明；有效失守MA10，转由符合条件的MA20守线或合格平台承接，否则退出。',
 'MA20横盘再启动':'最近一轮上涨≥20%且≥4 ATR后，回踩MA20不破或略破快速收回即可准入。MA20有效失守后，再核对至少5日、宽度≤2 ATR、缩量及保留上涨成果的固定平台；两道支撑都失守才退出。旧波段不作为当前阶段。',
 '趋势力度':'5/10/20日收益力度和连续结构的独立参考分，≥65为强。它不决定均线趋势入选，也不表示本轮启动日期。',
 '情绪强度':'当前模型：当日进攻60%、保持20%、近5日活跃20%，≥65为强。属于短线强度参考，尚不能单独证明连板、龙头或补涨潜力。',
 '趋势观察':'当前有合格均线阶段或推进延续证据；与情绪强度分别判断。',
 '趋势跟踪':'均线阶段仍在跟踪，但位置或整理结构当前未满足有效观察条件。阶段和具体偏离原因分别显示。',
 '情绪强势':'情绪强度达到固定门槛65，反映短线进攻、保持和近期活跃。',
 '趋势前排':'同一板块内趋势力度并列前三且力度≥65，是板块相对地位，不等于已证实的趋势龙头。',
 '情绪前排':'同一板块内情绪强度并列前三且强度≥65，是板块相对地位，不等于已证实的连板龙头。',
 '暂未强势':'有可用数据，但当前未满足趋势观察或情绪强势条件；完整成员排名仍保留。',
 '数据待核验':'必要数据不完整或口径尚未确认；缺失分数不当零，也不认定为弱股。',
 '守线观察':'本轮强势入口已确认，最新价格守住本阶段防守位；尚无当前底部反弹事件。',
 '接近支撑':'最新价格在本阶段防守位上方0.4 ATR以内，适合继续观察承接过程。',
 '暂无合格阶段':'当前没有通过强势入口和阶段条件的有效观察；完整板块排名仍保留。',
 'MA5失守·MA10承接观察':'MA5已有效失守，防守位改为MA10；不要求先完成三日紧缩平台才保留承接观察。',
 'MA10失守·MA20承接观察':'MA10已有效失守，本轮达到强势上涨门槛后转入MA20承接；优先守MA20，失守后由合格固定平台底部防守。',
 '底部反弹·再启动观察':'当前出现符合0.3 ATR门槛的底部反弹，进入再启动观察；平台上沿突破另行标注。',
 '支撑过程待核验':'价格触及或失守防守位，但连续分钟没有完整覆盖，暂不能证明15分钟修复或失效。',
 '日线待更新':'历史缺失交易日按停牌处理，使用实际取得的有效成交日继续判断；仅真实价格口径冲突暂停计算。',
 '报价待核验':'报价时间、批次、有效价格或最新性尚未通过核验。',
 '价格口径待核验':'现价与历史日线的复权、日期或来源口径尚未确认，暂停均线比较。',
 '平台观察到期':'横盘超过固定20个交易日窗口，原平台不再作为当前再启动观察。',
 '沿线推进不足':'最近完成日沿MA5保持次数或暂态MA5方向尚未达到推进条件。',
 '启动成果回吐':'现价回吐了本轮确认启动净上攻超过一半，当前不属于合格初期推进。',
 'MA20失守·平台承接':'最新价格低于MA20，但本轮上涨后形成的合格整理平台底部仍有效，继续观察，不因偏离MA20单独退出。',
 'MA20偏离过多':'现价低于MA20的幅度超出0.3 ATR与1.5%取小的允许范围；平台底部防守规则仍独立适用。',
 '支撑失守·修复观察':'价格暂低于本阶段防守位，等待连续15个交易分钟是否收回。午休不计时，分钟缺口不能证明超时。',
 '已退出':'MA10有效失守且无合格MA20承接，或MA20与合格平台底部均有效失守。15个交易分钟未收回、正式收盘失守或明显破位可确认；新的强势入口须重新验证。',
 '推进延续':'本轮阶段继续上攻，远离近线观察区或突破平台上沿；单列展示，不当成底部再启动。',
 '位置偏离':'阶段仍在跟踪，但现价离本阶段均线过远，暂不属于近线观察。',
 '整理结构扩散':'整理区间或量比超出固定门槛，当前不属于紧缩整理观察。',
 '均线仍向下':'暂态均线低于最新完成日均线，尚未符合承接阶段方向要求。',
 '启动待确认':'盘中价格突破，但当日量价尚未成为完成日数据，不能标为确认启动。',
 '放量上攻':'完成日单日上涨至少4%或连续两日至少6%，净上攻至少1.2 ATR，量比至少1.8，收盘位置至少75%。',
 '有效突破':'完成日收盘超过前20日最高价至少0.3 ATR，上涨至少3%、量比至少1.5、收盘位置至少75%。',
 '涨停突破':'已知主板涨停幅度，完成日收盘在最高价且接近涨停涨幅，收盘超过前20日最高价至少0.3 ATR。缩量封板可独立入选；普通上攻仍须放量。',
 '底部反弹':'在本阶段防守位或均线附近触底后，最新连续分钟或当日正式收盘反弹至少0.3 ATR。进入再启动观察，无需突破平台上沿。',
 '快速收回':'连续分钟显示短暂刺破后在15个交易分钟内收回；旧事件不冒充当前事件。',
 '降级至MA10':'MA5有效失守，继续以MA10为防守位承接观察。',
 '降级至MA20':'MA10有效失守，转入合格MA20观察：优先MA20，失守后才用本轮固定平台底部承接。',
 '收复MA5':'上轮有效报价在MA5下方，本轮回到MA5之上；仍结合本阶段防守位和整理结构。',
 '平台上沿突破':'现价超过锁定平台上沿至少0.3 ATR，归入推进延续。',
 '情绪进攻':'当日价格进攻较强；不能代替封板持续性与连板潜力验证。',
 '突破':'市场力度模型的突破形态，数值见完整依据；与完成日均线入口分别计算。',
 '再启动':'市场力度模型的再次转强形态；均线底部反弹另使用最新分钟或完成日证据。',
 '趋势推进':'当前市场力度和结构延续；均线阶段另行标注。',
 '回踩整理':'上涨后的回落整理，结合支撑、回落幅度和最新数据判断。',
 '明显回落':'相对阶段高点出现较大回落；风险信息不会因高强度分被忽略。',
 '新进入强势':'同日可比有效快照首次跨过强势门槛，使用源行情时间，网页刷新时间不作为发生时间。',
 '快照已过期':'快照已超过有效时间；保留成员与参考排名，等待更新后再作当前强势判断。'
};
function msExplain(label,evidence){var name=String(label||''),base=MS_EXPLANATIONS[name]||MS_EXPLANATIONS[name.replace(/\d+只$/,'')];if(!base&&name.indexOf(' / ')>=0)base=name.split(' / ').map(function(t){return MS_EXPLANATIONS[t]||t;}).join(' ');return (base||('后端状态“'+name+'”。'))+(evidence?' 当前依据：'+evidence:'');}
function msTipAttrs(label,evidence){return 'data-tip="'+esc(msExplain(label,evidence))+'" tabindex="0"';}
function msTag(label,evidence,cls){return '<span class="ms-tag '+(cls||'')+'" '+msTipAttrs(label,evidence)+'>'+esc(label)+'</span>';}
function msRecoveryCandidate(m){return m.recovery_current&&m.recovery_candidate&&m.recovery_candidate.active&&mtSnapshotFresh(m)?m.recovery_candidate:null;}
function msRecoveryTag(m){var c=msRecoveryCandidate(m);if(!c)return '';return '<span class="ms-tag ms-recovery-tag" '+msTipAttrs('涨停收复','本轮事件 '+c.date+'；第'+c.age_sessions+'/'+c.window_sessions+'个交易日；'+c.basis+'；事件量比 '+mtValue(c.volume_ratio)+'；最新核验 '+(m.quote_at||'—')+'；以候选MA10跟踪，尚未确认正式趋势')+'><span class="ms-recovery-dot" aria-hidden="true"></span><span>涨停收复</span><span class="ms-recovery-kind">候选</span></span>';}
function msCurrentMAStage(m){return !!(m&&m.stage&&m.status!=='已退出'&&!m.candidate_mode);}
function msMAStageLabel(m){return msCurrentMAStage(m)?m.stage_label:'暂无当前阶段';}
function msRankContext(){var v=MS_VIEW.stocks,selected=v.industryIds.concat(v.themeIds);if(STATE.boardFilterId&&selected.indexOf(STATE.boardFilterId)<0)selected.push(STATE.boardFilterId);var id=selected.indexOf(v.rankBoardId)>=0?v.rankBoardId:selected[0],b=id&&boardById(id);return {id:b?b.id:'all',name:b?b.name:'全池',board:b,ranking:((DATA.emotion_relay||{}).rankings||{})[b?b.id:'all']||(b?b.stock_ranking:(DATA.stock_board_ranking||{}).all),selected:selected};}
function msRankFresh(row,item){if(DATA.emotion_relay&&row.emotion_relay)return erFresh(row.emotion_relay);var m=row.market_strength||{},source=m.emotion_at||m.trend_at||item.source_at;if(m.trend_score==null&&m.emotion_score==null)return false;if(typeof sessionNow!=='function')return true;var at=parseDT(source);if(!at)return false;var mode=m.mode||'',formal=mode==='正式收盘',lunch=mode.indexOf('午休参考')===0;return mtSnapshotFresh({mode:lunch?'午休参考':mode,reference_only:mode.indexOf('参考行情')>=0,valid_until:formal?String(source).slice(0,10)+' 23:59:59':lunch?String(source).slice(0,10)+' 13:00:00':new Date(at.getTime()+600000).toISOString()});}
function msRankRows(){var v=MS_VIEW.stocks,ctx=msRankContext(),ranks=ctx.ranking||{},map={},fallback={};(DATA.stocks||[]).concat(DATA.coverage_catalog||[]).forEach(function(r){map[r.code]=r;});((ctx.board||{}).members||[]).forEach(function(r){fallback[r.code]=r;});return (ranks[v.sort==='trend'?'trend':v.sort==='emotion'?'emotion':'all']||[]).map(function(c){return map[c]||Object.assign({code:c,name:c,ranking_unavailable:true},fallback[c]||{});}).filter(function(r){var item=(ranks.items||{})[r.code]||{},m=r.market_strength||{},mt=r.ma_trend||{},tags=(m.labels||m.events||[]).concat(item.style_labels||[],mt.status==='已退出'?[]:mt.stage_label||[]);return (v.phase!=='涨停收复'||!!msRecoveryCandidate(mt))&&msMatchDirections(r)&&(!v.q||String(r.code+' '+r.name).indexOf(v.q)>=0)&&(!v.phase||tags.indexOf(v.phase)>=0)&&(v.scope==='all'||v.scope==='trend'&&item.trend&&mtSnapshotFresh(mt)||v.scope==='emotion'&&item.emotion&&msRankFresh(r,item)||v.scope==='focus'&&(item.trend&&mtSnapshotFresh(mt)||item.emotion&&msRankFresh(r,item))||v.scope==='both'&&item.trend&&mtSnapshotFresh(mt)&&item.emotion&&msRankFresh(r,item));});}
function msRankTools(){var ctx=msRankContext(),v=MS_VIEW.stocks,h='<div class="ms-toolbar">';if(ctx.selected.length>1)h+=msSelect('rankBoardId',ctx.selected.map(function(id){var b=boardById(id);return [id,b?b.name:id];}),'stocks','排名参照板块');return h+msSelect('scope',[['all','全部成员（默认）'],['trend','趋势观察'],['emotion',DATA.emotion_relay?'接力观察':'情绪强势'],['focus','任一观察'],['both','趋势与接力同时满足']],'stocks','成员范围')+msSelect('sort',[['board','板块地位优先'],['trend','趋势力度排序'],['emotion',DATA.emotion_relay?'接力地位排序':'情绪强度排序']],'stocks','个股排名方式')+msSelect('phase',[['','全部标签'],['MA5初期推进','MA5初期推进'],['MA10承接整理','MA10承接整理'],['MA20横盘再启动','MA20横盘再启动'],['涨停收复','涨停收复（近5日）'],['趋势前排','趋势前排'],...(DATA.emotion_relay?[['空间高标','空间高标'],['题材领先候选','题材领先候选'],['同身位竞争','同身位竞争'],['周期最高标','周期最高标'],['监管接续候选','监管接续候选'],['断板补涨候选','断板补涨候选'],['停牌接续候选','停牌接续候选'],['伴生关系观察','伴生关系观察'],['同题材前轮高标','同题材前轮高标'],['停牌核心观察','停牌核心观察']]:[['情绪前排','情绪前排']])],'stocks','个股标签')+'<input aria-label="强势搜索" placeholder="代码 / 名称" value="'+esc(v.q)+'" data-ms-search-key="stocks" data-ms-search-field="q" oninput="msSearchInput(event,this,\'stocks\',\'q\')"><button class="btn" onclick="msRankCSV()">导出当前完整排名 CSV</button></div><p class="ms-muted">排名参照：'+esc(ctx.name)+' · 确认主板成员 '+((ctx.ranking||{}).expected||0)+' 只；趋势力度有效 '+((ctx.ranking||{}).trend_valid||0)+'、'+(DATA.emotion_relay?'接力候选':'情绪有效')+' '+((ctx.ranking||{}).emotion_valid||0)+'。'+esc(DATA.emotion_relay?'综合参考顺序保留原排名；接力列按角色、高度、在板和反馈独立排序，不使用价格活跃分代表龙头地位。':DATA.stock_board_ranking.sorting)+' 多选时可切换排名参照板块，其他方向条件仍取交集。</p>';}
function msRankTable(rows,limit){var ctx=msRankContext(),ranking=ctx.ranking||{},shown=limit?rows.slice(0,limit):rows,h='<div class="tw"><table class="market-strength-table ms-research-table ms-rank-table"><thead><tr><th>板块排名</th><th class="l">个股 / 所属方向</th><th>当日涨幅</th><th>趋势力度 / 板块名次</th><th>'+(DATA.emotion_relay?'接力地位 / 板块名次':'情绪强度 / 板块名次')+'</th><th class="l">类型 / 均线阶段 / 状态</th></tr></thead><tbody>';
 shown.forEach(function(r){var m=r.market_strength||{},mt=r.ma_trend||{},item=(ranking.items||{})[r.code]||{},fresh=msRankFresh(r,item),labels=item.style_labels||[],tags=msRankStyleTags(r,item,ctx.name,fresh);tags+=msRecoveryTag(mt);if(mt.pending)tags+=msTag('数据待核验','均线阶段：'+mt.reason+'；情绪强度独立判断');if(!mt.stage&&msRecoveryCandidate(mt))tags+=msTag('MA10跟踪',mt.reason,'ms-follow-tag');if(msCurrentMAStage(mt))tags+=msTag(msMAStageLabel(mt),mt.reason+(mt.exit_at?'；历史退出 '+mt.exit_at:''))+' '+msTag(mt.status,mt.reason+(mt.exit_at?'；确认退出时间 '+mt.exit_at:''));if(item.missing||r.ranking_unavailable)tags+=msTag('数据待核验','该确认成员本轮没有完整个股数据');h+='<tr data-strength-id="'+esc(r.code)+'" data-board-rank="'+(item.rank||'')+'" class="clickable" onclick="showStock(\''+jsq(r.code)+'\')"><td><span class="ms-rank" '+msTipAttrs('板块地位',ctx.name+'完整成员第'+item.rank+'位，搜索和标签过滤不重算名次。')+'>'+(item.rank||'—')+'</span></td><td class="l"><b>'+esc(r.name||r.code)+'</b><span class="cd">'+esc(r.code)+'</span>'+msAffiliation(r,'stocks')+'</td><td>'+pctHtml(r.change_pct,2)+'</td><td>'+msBadge(m,'trend')+'<span class="cd">'+(item.trend_rank==null?'待核验':'板块第 '+item.trend_rank+' / '+ranking.trend_valid)+'</span></td><td>'+(DATA.emotion_relay?erRankCell(r,item,ranking):msBadge(m,'emotion')+'<span class="cd">'+(item.emotion_rank==null?'待核验':'板块第 '+item.emotion_rank+' / '+ranking.emotion_valid)+'</span>')+'</td><td class="l"><div class="ms-tag-list">'+tags+'</div><span class="cd">源行情 '+esc(item.source_at||'待核验')+'</span>'+'</td></tr>';});return h+'</tbody></table></div>'+msMore(rows,shown,'stocks');}
function msExportRows(rows,view,name){var ctx=msRankContext(),contexts={view:view,rankBoardId:ctx.id};if(!DATA.ui_lazy){downloadMSCSV(buildStockCSV(rows,DATA,contexts),name);return Promise.resolve();}var generation=DATA.ui_generation;return fetch('/__ui/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:generation,codes:rows.map(function(r){return r.code;}),contexts:contexts})}).then(function(r){if(!r.ok)throw new Error(r.status===409?'数据版本已过期，请更新后导出':'导出失败 '+r.status);return r.text();}).then(function(text){downloadMSCSV(text,name);}).catch(function(e){toast(e.message);throw e;});}
function msRankCSV(){return msExportRows(msRankRows(),'ranking','板块个股排名_'+DATA.ui_generation+'.csv');}
var MS_TOOLTIP=null,MS_TOOLTIP_TARGET=null;
function msShowTooltip(target){if(!target)return;if(!MS_TOOLTIP){MS_TOOLTIP=document.createElement('div');MS_TOOLTIP.id='ms-label-tooltip';MS_TOOLTIP.className='ms-label-tooltip';MS_TOOLTIP.setAttribute('role','tooltip');document.body.appendChild(MS_TOOLTIP);}var label=target.textContent.trim(),tip=target.getAttribute('data-tip')||msExplain(label,/ms-chip|ms-industry/.test(target.className)?'同花顺确认成员关系，点击方向查看完整成员排名。':'');MS_TOOLTIP.textContent=tip;MS_TOOLTIP.hidden=false;MS_TOOLTIP_TARGET=target;target.setAttribute('aria-describedby','ms-label-tooltip');var r=target.getBoundingClientRect(),x=Math.min(Math.max(8,r.left),window.innerWidth-MS_TOOLTIP.offsetWidth-8),y=r.bottom+8;if(y+MS_TOOLTIP.offsetHeight>window.innerHeight)y=Math.max(8,r.top-MS_TOOLTIP.offsetHeight-8);MS_TOOLTIP.style.left=x+'px';MS_TOOLTIP.style.top=y+'px';}
function msHideTooltip(){if(MS_TOOLTIP)MS_TOOLTIP.hidden=true;if(MS_TOOLTIP_TARGET)MS_TOOLTIP_TARGET.removeAttribute('aria-describedby');MS_TOOLTIP_TARGET=null;}
document.addEventListener('mouseover',function(e){var t=e.target.closest&&e.target.closest('[data-tip],.ms-chip,.ms-industry,.ms-return');if(t)msShowTooltip(t);else msHideTooltip();});
document.addEventListener('mouseout',function(e){if(MS_TOOLTIP_TARGET&&(e.target===MS_TOOLTIP_TARGET||MS_TOOLTIP_TARGET.contains(e.target))&&(!e.relatedTarget||!MS_TOOLTIP_TARGET.contains(e.relatedTarget)))msHideTooltip();});
document.addEventListener('mousemove',function(e){var t=e.target.closest&&e.target.closest('[data-tip],.ms-chip,.ms-industry,.ms-return');if(t&&(!MS_TOOLTIP||MS_TOOLTIP.hidden||MS_TOOLTIP_TARGET!==t))msShowTooltip(t);});
document.addEventListener('focusin',function(e){if(e.target.matches&&e.target.matches('[data-tip]'))msShowTooltip(e.target);});
document.addEventListener('focusout',function(e){if(MS_TOOLTIP_TARGET===e.target)msHideTooltip();});
document.addEventListener('scroll',function(){var t=MS_TOOLTIP_TARGET;if(!t)return;var r=t.getBoundingClientRect();if(t.isConnected&&r.width&&r.height&&r.bottom>0&&r.top<innerHeight)msShowTooltip(t);else msHideTooltip();},true);

function msRankStyleTags(row,item,name,fresh){var labels=(item.style_labels||[]).filter(function(t){return t!=='涨停收复';});if(!DATA.emotion_relay)return fresh?labels.map(function(t){return msTag(t,name+' · 源行情 '+(item.source_at||'待核验'));}).join(''):msTag('快照已过期');var m=row.emotion_relay||{},mt=row.ma_trend||{},relay=['接力观察','暂无接力事件'].concat(m.roles||[]),tags=labels.filter(function(t){return relay.indexOf(t)>=0?erFresh(m):mtSnapshotFresh(mt);}).map(function(t){return msTag(t,name+' · 源行情 '+(relay.indexOf(t)>=0?m.quote_at:mt.quote_at||item.source_at||'待核验'));}).join('');return tags||(!erFresh(m)&&!mtSnapshotFresh(mt)?msTag('快照已过期'):'');}
