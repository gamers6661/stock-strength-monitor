function buildStockCSV(res,DATA,contexts){
  contexts=contexts||{};
  if(contexts.view==='emotion'&&DATA.emotion_relay){
    var head=['代码','名称','已完成日截至','昨日完成板位','昨日板位完整','当前板位','当前板位完整','模式','当前在板','接力角色','事件','风险','今日涨幅%','真实涨停价','换手%','源行情','有效截至','接续参照','同题材关系','周期核心','全天停牌','最后成交日','伴生关系','异动披露与参考','规则版本','实现哈希','UI版本','完整接力依据'];
    var quote=function(v){return v==null?'':'"'+String(v).replace(/"/g,'""')+'"';};
    return '\ufeff'+head.join(',')+'\n'+res.map(function(r){var m=r.emotion_relay||{};return [r.code,r.name,m.prior_date,m.prior_height,m.prior_exact,m.height,m.height_exact,m.mode,m.sealed,(m.roles||[]).join(' / '),(m.events||[]).join(' / '),(m.risks||[]).join(' / '),m.feedback_pct,m.limit_price,m.turnover_pct,m.quote_at,m.valid_until,JSON.stringify(m.continuation||[]),JSON.stringify(m.relations||[]),JSON.stringify(m.cycle||{}),m.suspended_current,m.last_trade_date,JSON.stringify(m.companions||[]),JSON.stringify(m.regulation||{}),DATA.emotion_relay.version,DATA.emotion_relay.implementation_hash,DATA.ui_generation,JSON.stringify(m)].map(quote).join(',');}).join('\n');
  }
  function candidate(m){return m.recovery_current&&m.recovery_candidate&&m.recovery_candidate.active?m.recovery_candidate:{};}
  if(contexts.view==='ranking' && DATA.stock_board_ranking){
    var id=contexts.rankBoardId||'all',board=(DATA.board_stock_rankings||{})[id];
    if(!board&&id!=='all'){var found=(DATA.board_catalog||[]).filter(function(b){return b.id===id;})[0];if(found)board={name:found.name,ranking:found.stock_ranking};}
    var ranking=id==='all'?DATA.stock_board_ranking.all:board&&board.ranking||{},title=id==='all'?'全池':board&&board.name||id;
    if(DATA.emotion_relay)ranking=DATA.emotion_relay.rankings[id]||ranking;
    var columns=['代码','名称','参照板块','板块排名','趋势力度板块名次','情绪板块名次','趋势力度分','情绪强度分','类型标签','均线阶段','当前状态','当日涨幅%','行情源时间','本轮启动日','最近强势确认日','历史覆盖交易日','完成日截至','UI版本','排名规则版本','涨停收复候选日期','涨停收复候选状态','完整排名依据','完整均线依据'];
    if(DATA.emotion_relay){columns[5]='接力板块名次';columns[7]='价格活跃参考分';}
    var escapeCell=function(v){return v==null?'':'"'+String(v).replace(/"/g,'""')+'"';};
    return '\ufeff'+columns.join(',')+'\n'+res.map(function(r){var item=(ranking.items||{})[r.code]||{},ms=r.market_strength||{},mt=r.ma_trend||{};return [r.code,r.name,title,item.rank,item.trend_rank,item.emotion_rank,ms.trend_score,ms.emotion_score,(item.style_labels||[]).join(' / '),mt.stage_label,mt.status,r.change_pct,item.source_at,(mt.origin||{}).date,(mt.last_confirmation||mt.origin||{}).date,mt.history_days,mt.asof,DATA.ui_generation,DATA.stock_board_ranking.version,candidate(mt).date,candidate(mt).state,JSON.stringify(item),JSON.stringify(mt)].map(escapeCell).join(',');}).join('\n');
  }
  if(DATA.ma_trend){
    var head=['代码','名称','现价','当日涨幅%','均线阶段','当前状态','有效观察','本阶段支撑触线价','暂态均线','距支撑ATR','起点日期','起点通道','起点量比','起点实体ATR','整理量比','底部反弹ATR','反弹依据','同步方向','方向入选比例%','行情源时间','退出时间','原因','数据缺口','模式','均线版本','均线实现哈希','UI版本','情绪分','历史力度参考','防守依据','起点单日涨幅%','起点两日涨幅%','前段上涨%','前段上涨ATR','平台成立日','平台核验日','有效截至','涨停收复候选日期','涨停收复候选状态','完整均线依据'];
    var cell=function(v){return v==null?'':'"'+String(v).replace(/"/g,'""')+'"';};
    var lines=res.map(function(s){var m=s.ma_trend||{},o=m.origin||{},p=m.platform||{},b=m.board||{},rb=m.rebound||{},old=s.market_strength||{};return [s.code,s.name,m.price,m.change_pct,m.stage_label,m.status,m.eligible?'是':'否',m.support_price,m.ma_value,m.distance_atr,o.date,o.kind,o.volume_ratio,o.body_atr,m.volume&&m.volume.consolidation_ratio,rb.distance_atr,rb.basis,b.name,b.trend_pct,m.quote_at,m.exit_at,m.reason,(m.data_reasons||[]).join('；'),m.mode,m.version,DATA.ma_trend.implementation_hash,DATA.ui_generation,old.emotion_score,old.trend_score,m.support_basis,o.day_return_pct,o.two_day_return_pct,p.rise_pct,p.rise_atr,p.formed_at,p.validated_at,m.valid_until,candidate(m).date,candidate(m).state,JSON.stringify(m)].map(cell).join(',');});
    return '\ufeff'+head.join(',')+'\n'+lines.join('\n');
  }
  if(DATA.market_strength || res.some(function(s){return !!s.market_strength;})){
    var cols=['代码','名称','当日涨幅%','趋势分','情绪分','趋势等级','情绪等级','主导周期','阶段','事件','原因','风险','趋势截至','情绪截至','模式','规则版本','实现哈希','UI版本','完整模型依据'];
    var quote=function(v){return v==null?'': '"'+String(v).replace(/"/g,'""')+'"';};
    var rows=res.map(function(s){var m=s.market_strength||{};return [s.code,s.name,s.change_pct,m.trend_score,m.emotion_score,m.trend_level,m.emotion_level,m.dominant_period,m.phase,(m.events||[]).join('、'),(m.reasons||[]).join('；'),(m.risks||[]).join('；'),m.trend_at,m.emotion_at,m.mode,m.version,(DATA.market_strength||{}).implementation_hash,DATA.ui_generation,JSON.stringify(m)].map(quote).join(',');});
    return '\ufeff'+[cols.join(',')].concat(rows).join('\n');
  }
  function context(s){return contexts[s.code]||{};}
  function quoteFreshAtClientNow(s){return context(s).fresh;}
  function quoteStatusAtClientNow(s){return context(s).status;}
  function currentCandidateActive(s,key){return (context(s).candidates||{})[key];}
  function afternoonBridgeQuote(s){return context(s).bridge;}
  function morningOpenBridgeQuote(s){return context(s).openBridge;}
  function auctionDisplayQuote(s){return context(s).auction;}
  function closeDisplayQuote(s){return context(s).close;}
  function lunchDisplayQuote(s){return context(s).lunch;}
  function useCompletedClose(){return !!contexts.useCompletedClose;}
  var head=['代码','名称','判断日','日线进攻强度','日线强度分位','日线近期变化','综合状态','分位较前日变化','分位较前五日变化','5日攻击速度分','10日推进分','20日涨幅基础分','结构不计分','5日进攻依据','10日进攻依据','20日进攻依据','结构与量价依据','绝对方向','主要强项','主要短板','近10日跑赢主板天数','近3日收盘位置%','放量滞涨','当前距20日高点%','历史最大回撤修复%','5日相对优势变化百分点','20日涨幅%','20日涨幅分位','逐股报价时间','现价','今日涨跌%','双轴分类','趋势阶段','情绪热度','量价表现','行业状态','个股行业关系','趋势助攻','情绪助攻','个股角色','日线MA5','日线MA10','日线MA20','三线排列','日线趋势在线','完成日回踩形态','MA20近5日斜率%','20日最大回撤%','有方向20日路径效率','5日对市场超额百分点','20日对市场超额百分点','5日对同行超额百分点','20日对同行超额百分点','同行趋势在线%','同行趋势变化百分点','剔除前两名后趋势在线%','同行情绪活跃%','同行涨停数','行业','行业广度%','有效同伴','日线与历史风险'];
  head.push('扫描完成时间','盘中强度','相对评分变化','盘中趋势状态','盘中暂态MA5','盘中暂态MA10','盘中暂态MA20','日内位置%','距日内高点%','盘中风险等级','盘中风险标记','行业同期涨幅%','本股对同行超额点','历史回踩形态','当前回踩资格','报价是否有效','行情阶段','报价状态','最后有效报价时间','当日相对主板超额百分点','主板等权涨幅%','开盘后表现%','盘中评分完整项数','盘中观察分类','扫描状态变化','当前强势资格','初步启动资格','转弱修复资格','报价日前固定MA5','报价日前固定MA10','报价日前固定MA20','暂态MA20参考基准');
  head=head.map(function(name){return ({'当前回踩资格':'扫描时当前回踩资格',
    '当前强势资格':'扫描时当前强势资格','初步启动资格':'扫描时初步启动资格',
    '转弱修复资格':'扫描时转弱修复资格'})[name]||name;});
  function cell(x){return '"'+String(x==null?'':x).replace(/"/g,'""')+'"';}
  var lines=[head.map(cell).join(',')];
  res.forEach(function(s){var p=s.stock_strength_parts||{},e=s.stock_strength_evidence||{};
    lines.push([s.code,s.name,s.signal_date,s.stock_strength_score,s.stock_strength_percentile,s.daily_motion||s.stock_strength_motion,s.stock_strength_display_state,s.strength_delta1,s.strength_delta5,p.attack5,p.attack10,p.attack20,'',e.attack5,e.attack10,e.attack20,s.structure_evidence,s.strength_direction,s.stock_strength_main_good,s.stock_strength_main_weak,s.beat_days10,s.close_location3_pct,s.volume_spike_stall?'是':'否',s.current_drawdown_pct,s.drawdown_repair_pct,s.strength_accel5_pp,s.ret20,s.ret20_percentile,s.intraday_quote_at,s.price,s.change_pct,s.axis_group,s.trend_stage,s.emotion_heat,s.emotion_acceptance,s.industry_trend_state,s.industry_stock_relation,s.trend_assist,s.emotion_assist,(s.roles||[]).join('、'),s.ma5,s.ma10,s.ma20,s.trend_aligned?'是':'否',s.trend_online?'是':'否',s.touch_state,s.ma20_slope5_pct,s.max_dd20_pct,s.path_eff20,s.ret5_ex_market,s.ret20_ex_market,s.ret5_ex_industry,s.ret20_ex_industry,s.industry_peer_trend_pct,s.industry_peer_trend_delta_pp,s.industry_ex_top2_trend_pct,s.emotion_peer_active_pct,s.emotion_peer_limit,s.primary_industry,s.industry_breadth,s.industry_peers,(s.risk_notes||[s.reason_text||'']).join('；'),DATA.scan_completed_at||DATA.generated_at,s.intraday_score,s.intraday_score_delta,s.intraday_trend_state,s.intraday_ma5,s.intraday_ma10,s.intraday_ma20,s.intraday_position_pct,s.intraday_drawdown_from_high_pct,s.intraday_risk_level,(s.intraday_risk_flags||[]).join('；'),s.industry_intraday_change_pct,s.industry_intraday_excess_pct,s.historical_pullback_shape?'是':'否',s.current_pullback_candidate?'是':'否',s.intraday_quote_fresh?'是':'否',s.intraday_phase_status,s.intraday_quote_status,s.last_valid_quote_at,s.intraday_relative_return_pct,s.intraday_market_return_pct,s.intraday_open_return_pct,s.intraday_score_available_components,s.intraday_observation_state,s.intraday_transition,s.current_strong_candidate?'是':'否',s.startup_candidate?'是':'否',s.turn_weak_repair_candidate?'是':'否',s.daily_ma5_fixed,s.daily_ma10_fixed,s.daily_ma20_fixed,s.intraday_previous_completed_ma20].map(cell).join(','));});
  lines[0]+=',10日涨幅%,日线价格形态,盘中暂态进攻分,盘中暂态进攻档,盘中价格形态,进攻监测候选,进攻状态时间口径';
  res.forEach(function(s,i){lines[i+1]+=','+[s.ret10,s.daily_attack_stage,s.live_attack_score,s.live_attack_tier,s.live_attack_stage,s.attack_watch_candidate?'是':'否',s.live_attack_status].map(cell).join(',');});
  lines[0]+=',同花顺题材关系,题材关系状态,题材有效同伴覆盖,题材归属依据,全体强度名次,趋势池名次,趋势池分位,关注层级,行业归属来源,历史报价口径差异百分点,历史报价口径状态,扫描转换核验,当前强势未通过项';
  res.forEach(function(s,i){lines[i+1]+=','+[(s.theme_relations||[]).map(function(t){return t.name;}).join('、'),(s.theme_relations||[]).map(function(t){return t.name+':'+t.state;}).join('；'),(s.theme_relations||[]).map(function(t){return t.name+' '+t.peers+'只';}).join('；'),s.theme_basis,s.stock_strength_rank,s.trend_pool_rank,s.trend_pool_percentile,s.trend_tier,s.industry_basis,s.intraday_price_basis_gap_pct,s.intraday_price_basis_status,s.intraday_transition_state,(s.current_strong_missing||[]).join('；')].map(cell).join(',');});
  lines[0]+=',当前报价状态,当前强势候选,当前回踩候选,当前初步启动候选,当前转弱修复候选';
  res.forEach(function(s,i){lines[i+1]+=','+[
    quoteFreshAtClientNow(s)?'报价有效':quoteStatusAtClientNow(s),
    currentCandidateActive(s,'current_strong_candidate')?'是':'否',
    currentCandidateActive(s,'current_pullback_candidate')?'是':'否',
    currentCandidateActive(s,'startup_candidate')?'是':'否',
    currentCandidateActive(s,'turn_weak_repair_candidate')?'是':'否'
  ].map(cell).join(',');});
  lines[0]+=',最近完成日日期,最近完成日收盘价,最近完成日涨跌幅%,页面展示口径,页面展示时间,页面展示价格,页面展示涨跌幅%';
  res.forEach(function(s,i){
    var bridge=afternoonBridgeQuote(s);
    var openBridge=morningOpenBridgeQuote(s),auction=auctionDisplayQuote(s);
    var shown=useCompletedClose()?closeDisplayQuote(s):lunchDisplayQuote(s)||bridge||openBridge||auction;
    lines[i+1]+=','+[s.last_completed_date,s.last_completed_close,s.last_completed_change_pct,
      bridge?'午后报价待更新·11:30参考':openBridge?'开盘报价待更新·'+openBridge.kind:shown?shown.kind:'当日报价',shown?shown.at:s.intraday_quote_at,
      shown?shown.price:s.price,shown?shown.change:s.change_pct].map(cell).join(',');
  });
  lines[0]+=','+['价格进攻分','价格进攻档位','距盘中MA5_ATR'].map(cell).join(',');
  res.forEach(function(s,i){var f=s.live_attack_fund||{};lines[i+1]+=','+[s.live_attack_price_score,s.live_attack_price_tier,s.live_overheat_dist_atr].map(cell).join(',');});
  lines[0]+=','+['盘中判断截至','盘中本轮判断可用','日内路径状态','累计获取次数','有效获取次数','MA10扫描变化记录'].map(cell).join(',');
  res.forEach(function(s,i){var p=s.intraday_path||{};lines[i+1]+=','+[s.intraday_judgment_at,s.intraday_observation_available?'是':'否',p.state,p.acquired_count,p.valid_count,(p.events||[]).map(function(e){return e.at+' '+e.kind;}).join('；')].map(cell).join(',');});
  lines[0]+=','+['整理资格','整理状态','整理结构标签','此前5日进攻%','进攻窗口截至','整理开始日','整理完成日数','整理形态','整理日线回撤ATR','整理量对上涨量','整理振幅变化','整理固定平台上沿','整理转强确认次数','整理突破确认次数','整理判断截至','整理未通过原因'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.trend_consolidation||{};lines[i+1]+=','+[c.completion_confirmed?(c.trend_exited?'已转强，MA20失守退出':c.reference_only&&String(c.stage||'').indexOf('待核验')>=0?'已转强，待核验':'已完成整理，进入转强跟踪'):c.eligible===true?'日线资格通过':c.eligible===false?'未通过':'未重判',c.stage,c.trend_label,c.impulse5_pct,c.impulse_end,c.consolidation_start,c.days,c.shape,c.pullback_atr,c.volume_ratio,c.contraction_ratio,c.platform_high,c.turn_samples,c.breakout_samples,c.quote_at,c.reason].map(cell).join(',');});
  lines[0]+=','+['此前10日进攻%','整理进攻达标周期','整理进攻达标涨幅%','整理后再突破日数','整理历史放量分歧日','整理MA10历史失守已修复','整理修复价','整理修复有效采样次数','整理结构说明'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.trend_consolidation||{};lines[i+1]+=','+[c.impulse10_pct,c.attack_period,c.attack_gain_pct,c.post_breakout_days,(c.expanded_down_dates||[]).join('；'),c.ma10_repaired?'是':'否',c.repair_trigger_price,c.repair_samples,c.structure_note].map(cell).join(',');});
  lines[0]+=','+['历史转强确认','历史转强确认时间','转强后当前状态','本轮进攻确认','跟踪MA10边界','MA10连续失守次数','MA10连续收复次数','MA20退出时间','MA20修复时间','收盘复核日','收盘复核价（日线口径）','收盘MA10（日线口径）','收盘复核价格口径'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.trend_consolidation||{};lines[i+1]+=','+[c.completion_confirmed===true?'是':'否',c.completed_at,c.tracking_state,c.current_breakout_confirmed===true?'是':c.completion_confirmed?'否':'',c.tracking_ma10,c.ma10_below_samples,c.ma10_recovery_samples,c.trend_exit_at,c.trend_recovered_at,c.close_review_day,c.close_review_price,c.close_review_ma10,c.close_review_price_basis].map(cell).join(',');});
  lines[0]+=','+['已整理完成交易日数','整理天数截至','当日整理序号','回踩反弹参考均线','回踩靠线日期时间','回踩反弹确认日期时间','回踩反弹证据','回踩反弹当前保持'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.trend_consolidation||{};lines[i+1]+=','+[c.consolidation_elapsed_days,c.consolidation_elapsed_asof,c.consolidation_day_number,c.rebound_line?'MA'+c.rebound_line:'',c.rebound_touch_at,c.rebound_confirmed_at,c.rebound_evidence,c.rebound_active===true?'是':c.rebound_confirmed?'否':''].map(cell).join(',');});
  lines[0]+=','+['跟踪MA20边界','MA20连续失守次数','MA20连续收复次数','收盘MA20（日线口径）','MA10降级','支撑位置提示','提示截至','提示价格口径','平台底部（提示口径）','旧规则MA10退出留档'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.trend_consolidation||{};lines[i+1]+=','+[c.tracking_ma20,c.ma20_below_samples,c.ma20_recovery_samples,c.close_review_ma20,c.ma10_downgraded===true?'是':'否',(c.support_alerts||[]).map(function(a){return a.label+' ¥'+a.price+' 距'+a.distance_atr+'ATR';}).join('；'),c.support_alert_at,c.reference_only&&c.close_review_day&&c.support_alert_at===c.close_review_day+' 15:00:00'?'同源正式日线':'已核验报价',c.support_platform_low,c.legacy_ma10_exit_at].map(cell).join(',');});
  lines[0]+=','+['量价结构版本','固定周期编号','完成日结构','结构证据截至','原平台上沿','原平台下沿','固定ATR20','量能参考','结构价格口径','盘中平台上沿','盘中突破门槛','盘中结构观察','盘中结构截至','当前结构限制','失败事件数'].map(cell).join(',');
  res.forEach(function(s,i){var w=s.wyckoff_structure||{};lines[i+1]+=','+[w.version,w.cycle_id,w.label,w.evidence_asof,w.platform_high,w.platform_low,w.atr0,w.volume0,w.price_basis,w.live_platform_high,w.live_breakout_threshold,w.live_label,w.live_at,(w.restrictions||[]).join('；'),(w.events||[]).filter(function(e){return e.kind==='breakout_failed'||e.kind==='structure_closed';}).length].map(cell).join(',');});
  lines[0]+=','+['衔接模型','昨收基准日','昨收主榜','昨日日线档位','当日综合判断','衔接报价截至','当前价格进攻分','价格距昨收ATR','衔接风险','ATR算法','前日变化来源','前五日变化来源','威科夫特征'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.session_context||{},w=s.wyckoff_structure||{};lines[i+1]+=','+[c.version,c.previous_close_asof,c.previous_close_board?'是':'否',c.prior_daily_tier,c.label,c.quote_at,c.price_attack_score,c.gap_atr,(c.risks||[]).join('；'),c.atr_method,s.strength_delta1_source,s.strength_delta5_source,(w.wyckoff_evidence||{}).label].map(cell).join(',');});
  lines[0]+=','+['最新价格判断','当前平台状态','报价判断模式','整理条件状态','整理条件依据','本地日线数','历史窗口核验','当前原平台突破门槛','已完成整理日数'].map(cell).join(',');
  res.forEach(function(s,i){var c=s.session_context||{},e=c.history_evidence||{};lines[i+1]+=','+[c.current_label,c.structure_state,c.observation_mode,c.setup_state,c.setup_reason,e.count,e.valid===true?'已核验':e.reason,c.breakout_threshold,c.completed_consolidation_days].map(cell).join(',');});
  lines[0]+=','+['雷达规则版本','雷达数据版本','雷达当前资格','雷达主标签','雷达全部标签','雷达状态','雷达源报价','雷达R0%','雷达E0百分点','雷达M0%','雷达事件与完整依据'].map(cell).join(',');
  res.forEach(function(s,i){var r=s.radar_opportunity||{};lines[i+1]+=','+[r.version,DATA.ui_generation,r.current,r.main_label,(r.labels||[]).join('、'),r.status,r.source_at,r.R0,r.E0,r.M0,JSON.stringify(r)].map(cell).join(',');});
  return '\ufeff'+lines.join('\n');
}
if(typeof module!=='undefined'&&module.exports){
  module.exports=buildStockCSV;
  if(require.main===module){
    var input='';process.stdin.setEncoding('utf8');
    process.stdin.on('data',function(s){input+=s;});
    process.stdin.on('end',function(){var j=JSON.parse(input);process.stdout.write(buildStockCSV(j.rows,j.data,j.contexts));});
  }
}
