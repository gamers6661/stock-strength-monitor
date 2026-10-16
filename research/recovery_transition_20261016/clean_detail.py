from pathlib import Path
p=Path(__file__).resolve().parents[2]/'ma_trend_ui.js'
s=p.read_text(encoding='utf8');start=s.index('function mtDetail(m){');end=s.index('\nfunction mtDefense',start)
replacement=r'''function mtDetail(m){
 if(!m||mtHistorical(m))return '';
 if(msRecoveryCandidate(m))return mtRecoveryDetail(m);
 if(m.candidate_mode)return '<details class="card ma-trend-detail"><summary>候选核验状态 · '+esc(mtSnapshotFresh(m)?m.status:'快照已过期')+'</summary><p>当前无有效涨停收复候选标签。'+esc(m.reason||'等待最新报价及支撑核验')+'</p><p class="ms-muted">源行情 '+esc(m.quote_at||'待更新')+'</p></details>';
 var p=mtModel().parameters,o=m.origin||{},pl=m.platform||{},rise=m.ma20_entry||pl,rb=m.rebound||{},h=[];
 h.push('<p>'+esc(m.mode)+' · 源报价 '+esc(m.quote_at||'—')+' · 完成日 '+esc(m.asof||'—')+'</p>');
 if(m.reason)h.push('<p>'+esc(m.reason)+'</p>');
 if((m.events||[]).length)h.push('<p>'+esc(m.events.join(' / '))+'</p>');
 if(m.support_price!=null)h.push('<p>防守依据 '+esc(m.support_basis||'—')+' · 本阶段支撑触线价 '+mtValue(m.support_price,4)+' · 暂态均线 '+mtValue(m.ma_value,4)+'</p>'+mtDefense(m));
 if(o.confirmation)h.push(mtConfirmation(m));
 else if(o.date)h.push('<p><b '+msTipAttrs(o.kind)+'>'+esc(o.kind)+'</b> · '+esc(o.basis||'')+'</p>'+mtDates(m)+'<p>单日上涨 '+pctHtml(o.day_return_pct)+' / 两日 '+pctHtml(o.two_day_return_pct)+'；'+(o.rise_days||'—')+'日净上攻 '+mtValue(o.rise_atr)+' ATR（放量上攻门槛 '+p.impulse_rise_atr+'）；量比 '+mtValue(o.volume_ratio)+'（上攻 '+p.volume_ratio+' / 突破 '+p.breakout_volume_ratio+'）；收盘位置 '+mtValue(o.close_position==null?null:o.close_position*100,1)+'%</p>');
 h.push('<p class="ms-muted">实际覆盖 '+(m.history_days||'—')+' 个完成交易日（'+esc(m.history_from||'—')+' 至 '+esc(m.asof||'—')+'）</p>');
 if(rise.rise_pct!=null)h.push('<p>前段上涨 '+pctHtml(rise.rise_pct)+' / '+mtValue(rise.rise_atr)+' ATR；固定低点 '+mtValue(rise.base_low)+'（'+esc(rise.base_at||'—')+'）</p>');
 if(pl.latest_cycle)h.push('<p>最近上涨 '+esc(pl.rise_start||pl.base_at||'—')+' → '+esc(pl.rise_end||pl.peak_date||'—')+'；整理起于 '+esc(pl.start||'—')+'；平台底部保留 '+pctHtml(pl.retained_pct)+' / '+mtValue(pl.retained_atr)+' ATR。振幅 '+mtValue(pl.width_pct)+'%（超过10%仅提示），宽度 '+mtValue(pl.width_atr)+' ATR（≤2）。</p>');
 if(pl.start)h.push('<p>'+esc(pl.confirmed?'锁定后备平台':m.stage===20?'暂无合格后备平台，当前以MA20防守':'承接区间（平台尚未确认）')+' '+mtValue(pl.low)+' 至 '+mtValue(pl.high)+' · 成立 '+esc(pl.formed_at||'—')+' · 最近核验 '+esc(pl.validated_at||'—')+' · 当前 '+(pl.current_days||pl.days||'—')+' 日 · 整理量比 '+mtValue(m.volume&&m.volume.consolidation_ratio)+'</p>');
 else if(m.stage===20)h.push('<p class="ms-muted">后备平台尚未形成，当前以MA20防守。</p>');
 if(rb.distance_atr!=null)h.push('<p>本次底部反弹 '+mtValue(rb.distance_atr)+' ATR（门槛 '+p.rebound_atr+'） · '+esc(rb.basis)+' · '+esc(rb.at||'—')+'</p>');
 if(m.stage===20)h.push('<p>MA20首次回收允许略破 '+p.ma20_below_atr+' ATR与'+p.ma20_below_pct+'%取小；MA20失守后，合格平台底部才作为第二道支撑。</p>');
 h.push('<p class="ms-card-risk">'+(m.mode==='正式收盘'?'正式收盘按最终完成日线确认阶段及支撑；MA5失守转MA10，MA10无合格MA20承接则退出；MA20与合格平台均失守才退出。分钟过程不覆盖收盘结论。':'盘中失守 '+p.repair_minutes+' 个交易分钟未收回：MA5转MA10，MA10无合格MA20承接则退出，MA20与合格平台均失守退出；明显跌破 '+p.break_atr+' ATR提前退出。')+'</p>');
 if(m.minute_coverage)h.push('<p>分钟来源 '+esc(m.minute_coverage.source)+' · 覆盖 '+esc(m.minute_coverage.first_at)+' 至 '+esc(m.minute_coverage.last_at)+' · '+m.minute_coverage.bars+' 条'+(m.minute_coverage.no_trade_minutes?'；累计成交量与成交额均未变化，已核验无成交 '+m.minute_coverage.no_trade_minutes+' 分钟':'')+'；对应报价 '+esc(m.minute_coverage.quote_at)+'</p>');
 h.push('<p class="ms-muted">'+esc((m.data_reasons||[]).join('；')||'当前必要数据已核验')+'</p><details><summary>完整阶段、支撑与分钟依据</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(JSON.stringify(m,null,2))+'</pre></details>');
 return '<details class="card ma-trend-detail"><summary>均线趋势判断依据 · '+esc(m.stage_label)+' · '+esc(m.status)+'</summary><div>'+h.join('')+'</div></details>';
}'''
p.write_text(s[:start]+replacement+s[end:],encoding='utf8')
