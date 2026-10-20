"""将前一完成日结构、收盘留档与当日报价结合；竞价也生成明确的价格判断。"""
from collections import Counter
from datetime import datetime
import json

import attack_model
import close_monitor
import config
import intraday
import stock_strength
import history_reference

VERSION='收盘衔接与竞价观察5-末段保留'
ATR_METHOD='ATR20-SMA：20个含跳空的真实波幅简单平均'

def close_baseline(day):
    try:record=json.loads((close_monitor.CLOSE_DIR/(str(day)+'.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    if record.get('version')!=close_monitor.VERSION or record.get('asof')!=day or record.get('strength_version')!=stock_strength.VERSION:return {}
    return {r['code']:r for r in record.get('stocks') or []}

def daily_baseline(day):
    try:record=json.loads(stock_strength._daily_path(day).read_text(encoding='utf-8'))
    except (OSError,ValueError):record={}
    if record.get('version')!=stock_strength.VERSION or record.get('asof')!=day:record=history_reference.load(day)
    return record.get('stocks') or {}

def live_quote(q,captured_at,session):
    at=intraday.parse_quote_timestamp(q.get('quote_at') or q.get('ts'),captured_at)
    if at is None:return None,'逐股报价时间缺失'
    age=(captured_at-at).total_seconds();minute=at.hour*60+at.minute
    auction=session in ('集合竞价','竞价结束')
    retained=(session=='午间休市' and 690<=minute<780) or (session=='已收盘' and 900<=minute<960)
    limit=24*60*60 if retained else config.INTRADAY['max_quote_age_seconds'] if session=='竞价结束' and 565<=minute<570 else 120 if auction else config.INTRADAY['max_quote_age_seconds']
    if at.date()!=captured_at.date():return None,'当日逐股报价尚未到达'
    if age < -config.INTRADAY['max_quote_future_seconds'] or age>limit:return None,'逐股报价时间超出本阶段有效窗口'
    allowed=(555<=minute<570) if auction else ((570<=minute<=690) or (780<=minute<=900) or retained)
    if not allowed or session not in ('集合竞价','竞价结束','早盘','午盘','尾盘','午间休市','已收盘'):return None,'当前阶段只展示完成日结构'
    if not intraday._positive(q.get('price')):return None,'当日报价无有效价格'
    if not auction and not (intraday._positive(q.get('amount_wan')) or intraday._positive(q.get('volume_shou'))):
        return None,'连续交易尚无有效成交'
    return at,None

def history_evidence(bars,calendar,asof):
    bars=sorted((b for b in bars if b.get('date','')<=str(asof)),key=lambda b:b['date'])
    window=bars[-40:];dates=[d for d in calendar if d<=str(asof)][-40:]
    modes={(b.get('price_basis'),b.get('price_basis_source')) for b in window}
    allowed={('qfq',s) for s in intraday._QFQ_HISTORY_SOURCES}|{('raw',s) for s in intraday._RAW_HISTORY_SOURCES}
    issue=('整理参考需40根完成日线，目前'+str(len(bars))+'根' if len(window)<40 or len(dates)<40 else
           '整理参考窗口有交易日缺口或重复' if [b['date'] for b in window]!=dates else
           '整理历史来源或复权口径待核验' if len(modes)!=1 or not modes.issubset(allowed) else
           '整理历史OHLC无效' if not all(intraday._valid_historical_price_bar(b) for b in window) else None)
    return dict(count=len(bars),required=40,asof=bars[-1]['date'] if bars else None,valid=issue is None,reason=issue)

def current_structure(item,row,basis,upper,lower,buffer,auction):
    """用这次已核验报价解释当前结构；正式整理条件与缺数据分开。"""
    price=item['price'];ma=basis['provisional_ma']
    pattern=attack_model.price_pattern(basis['aligned_bars'],price,ma[10],item['gap_pct'],live=True)
    item['current_pattern']=pattern
    item['current_ma10']=ma[10];item['current_ma20']=ma[20]
    item.update(platform_high=upper,platform_low=lower,breakout_threshold=upper+buffer if upper else None)
    if intraday._positive(lower) and price<lower:
        state='现价跌穿原平台下沿'
        item['risks'].append(state)
    elif intraday._positive(upper):
        state=('现价越过原平台突破门槛' if price>upper+buffer else
               '现价在平台上沿，尚未越过突破门槛' if price>=upper else
               '原平台内承接' if price>=item['prior_close'] else '原平台内回踩')
    else:state='尚无已确认整理平台'
    item['structure_state']=state
    if price<ma[20]:label='现价失守MA20'
    elif price<ma[10]:label='现价失守MA10'
    elif state=='现价跌穿原平台下沿':label=state
    elif state=='现价越过原平台突破门槛':label='现价突破原平台，待成交量与收盘确认'
    else:label=pattern['stage']
    item['current_label']=('竞价'+label if auction else label)
    if not auction:item['label']=label
def setup_evidence(item,row):
    c=row.get('trend_consolidation') or {};e=item['history_evidence']
    item['setup_state']=('历史数据待补齐' if not e['valid'] or c.get('pending') and not c.get('eligible') else
                         '已形成整理平台' if c.get('eligible') or c.get('completion_confirmed') else
                         '尚未形成整理' if c.get('stage')=='尚未形成整理' or '至少2个完成交易日' in c.get('reason','') else '整理条件未满足')
    item['setup_reason']=e['reason'] if not e['valid'] else c.get('reason') or ('历史整理已确认，结合最新价格观察' if c.get('eligible') or c.get('completion_confirmed') else '未形成合格整理平台')
    item['completed_consolidation_days']=c.get('completed_consolidation_days',c.get('consolidation_elapsed_days',c.get('days')))

def attach(snap,quotes,series,calendar,contexts=None,baseline=None):
    contexts=contexts or {};day=(snap.get('strength_model') or {}).get('asof')
    observed_at=snap.get('quote_capture_at') or snap.get('generated_at')
    now=datetime.fromisoformat(observed_at)
    previous_day=max((d for d in calendar if d<now.date().isoformat()),default=day)
    baseline=close_baseline(previous_day) if baseline is None else baseline
    prior_daily=daily_baseline(previous_day) if day!=previous_day else {}
    session=snap.get('session');auction=session in ('集合竞价','竞价结束')
    rows=(snap.get('stocks') or [])+(snap.get('coverage_catalog') or [])
    returns={};items=[]
    for row in rows:
        code=row['code'];q=dict(quotes.get(code) or {})
        at,issue=live_quote(q,now,session)
        basis=contexts.get(code) or intraday.align_price_basis(q,series.get(code,[]),calendar,
                    observation_day=now.date().isoformat(),quote_at=at,allow_partial=True)
        prior=baseline.get(code)
        item=dict(version=VERSION,code=code,name=row.get('name',code),stage=session,
                  previous_close_asof=previous_day,previous_close_board=bool(prior),background_asof=day,
                  prior_daily_tier=(prior_daily.get(code) or {}).get('tier') if day!=previous_day else row.get('daily_attack_tier'),
                  background_tier=row.get('daily_attack_tier'),prior_trend_online=row.get('trend_online')==1 if day==previous_day else None,
                  prior_strength_score=(prior_daily.get(code) or {}).get('score') if day!=previous_day else row.get('stock_strength_score'),
                  baseline_source='真实收盘主榜与同源完成日线' if prior else '同源完成日线（该股不在昨日收盘主榜）',
                  quote_at=at.isoformat(sep=' ',timespec='seconds') if at else None,
                  price=q.get('price') if at else None,quote_valid=at is not None,
                  price_basis_valid=basis.get('valid') is True,atr_method=ATR_METHOD,
                  atr20=basis.get('atr20') if basis.get('valid') else None,
                  gap_pct=None,gap_atr=None,prior_close=None,ma10=None,ma20=None,
                  provisional_trend=None,price_attack_score=None,price_attack_tier=None,
                  monitor_candidate=False,risks=[],reason=issue or basis.get('reason'),
                  history_evidence=history_evidence(series.get(code,[]),calendar,day),
                  current_label=None,structure_state=None,setup_state=None,
                  observation_mode='午间最新报价参考' if session=='午间休市' else '收盘报价参考' if session=='已收盘' else '当日报价判断',
                  label='当日报价尚未到达' if session in ('集合竞价','竞价结束','早盘','午盘','尾盘','午间休市','已收盘') else '完成日结构参考')
        setup_evidence(item,row)
        row['session_context']=item;items.append(item)
        if at is None:continue
        price=q['price'];last_close=q.get('last_close')
        known_quote=(q.get('price_basis')=='raw' and q.get('price_basis_source') in intraday._RAW_QUOTE_SOURCES and
                     q.get('last_close_semantics')=='previous_trade_day_raw_close' and intraday._positive(last_close))
        if known_quote:item['gap_pct']=(price/last_close-1)*100
        if not basis.get('valid'):
            item['label']=('竞价' if auction else '当日')+('高开/上涨' if (item['gap_pct'] or 0)>0 else
                         '低开/下跌' if (item['gap_pct'] or 0)<0 else '价格观察')+'，结构口径待核验'
            item['current_label']=item['label']
            continue
        bars=basis['aligned_bars'];close=bars[-1]['close'];a=basis.get('atr20')
        item.update(prior_close=close,previous_close_asof=basis.get('expected_history_date'),
                    gap_pct=(price/close-1)*100,gap_atr=(price-close)/a if intraday._positive(a) else None,
                    ma10=basis['daily_ma'][10],ma20=basis['daily_ma'][20])
        ma=basis['provisional_ma']
        if len(bars)<20 or not all(intraday._positive(ma.get(n)) for n in (5,10,20)) or not intraday._positive(basis['daily_ma'].get(20)):
            item.update(partial_history=True,available_ma={str(n):ma.get(n) for n in (5,10,20)},
                label=('竞价' if auction else '当日')+'价格观察 · '+str(len(bars))+'根有效日线',
                current_label='有效样本观察',reason='按已有有效成交日展示；尚未形成的均线周期不参与比较')
            continue
        trend=bool(ma[5]>ma[10]>ma[20] and ma[20]>basis['daily_ma'][20] and price>=ma[10])
        item['provisional_trend']=trend
        returns[code]={n:(price/bars[-n]['close']-1)*100 for n in (5,10,20)}
        strong=bool(prior or item['prior_daily_tier'] in ('A','B'))
        structure=row.get('wyckoff_structure') or {}
        upper=structure.get('live_platform_high')
        lower=structure.get('live_platform_low')
        if not intraday._positive(upper) and not structure.get('pending_reason') and structure.get('state') not in ('closed','expired'):
            # 竞价不借用昨日raw边界；从已核验的今日比例换算固定原平台。
            cycle=structure.get('platform_high');factor=structure.get('price_scale_factor',1.0)
            if intraday._positive(cycle) and intraday._positive(factor):upper=cycle*factor*basis['scale_factor']
            if intraday._positive(structure.get('platform_low')) and intraday._positive(factor):lower=structure['platform_low']*factor*basis['scale_factor']
        buffer=max(.1*(structure.get('atr0') or 0)*structure.get('price_scale_factor',1.0)*basis['scale_factor'],.01)
        if price<ma[20]:
            item['label']='竞价结构转弱' if auction else '昨日结构、今日跌破MA20'
            item['risks'].append('现价失守盘中MA20')
        elif price<ma[10]:
            item['label']='竞价失守MA10' if auction else ('昨日强股、今日失守MA10' if strong else '昨日结构、今日失守MA10')
            item['risks'].append('现价失守盘中MA10')
        elif intraday._positive(upper) and price>upper+max(.1*(structure.get('atr0') or 0)*structure.get('price_scale_factor',1.0)*basis['scale_factor'],.01):
            item['label']='竞价越过原平台' if auction else '昨日整理、今日越过原平台'
        elif strong and price>=close:
            item['label']='强股竞价承接' if auction else '昨日强股、今日延续'
        elif strong:
            item['label']='强股竞价回踩' if auction else '昨日强股、今日回踩'
        else:
            item['label']=(('竞价' if auction else '当日')+'价格转强观察' if price>close and trend else
                           '竞价平台内观察' if auction else '当日价格与历史结构观察')
        current_structure(item,row,basis,upper,lower,buffer,auction)
        if intraday._positive(a) and (price-ma[5])/a>3.5:item['risks'].append('现价距盘中MA5过远，位置偏热')
        if row.get('trade_status') in ('no_trade','trade_recovered_wait_daily'):
            item['risks'].append('此前成交受限，今日成交状态需核验')
        if not intraday._positive(a):item['risks'].append(basis.get('atr20_reason') or 'ATR20尚未可核验')
        if not auction:item['risks']+=list(row.get('intraday_risk_flags') or [])
        item['risks']=list(dict.fromkeys(item['risks']))
        item['reason']=('价格判断已结合昨日收盘与20日结构；竞价虚拟匹配/未匹配量未获核验，不能确认量价突破'
                        if auction else '昨日收盘背景结合当前价格、暂态趋势及风险')
        if auction:item['auction_phase']=('竞价末价' if at.hour*60+at.minute>=565 else
                                         '不可撤单阶段' if at.hour*60+at.minute>=560 else '可撤单阶段')
    scored=attack_model.momentum_scores(returns)
    for item in items:
        score=scored.get(item['code'])
        if not score:continue
        item['price_attack_score']=score['score']
        item['price_attack_tier']=attack_model.tier(score['score'],returns[item['code']],item['provisional_trend'])
        item['monitor_candidate']=bool(session in ('集合竞价','竞价结束','早盘','午盘','尾盘') and item['quote_valid'] and item['gap_pct']>0 and item['provisional_trend'] and
                            (item['prior_daily_tier'] in ('A','B') or item['previous_close_board'] or item['price_attack_tier']=='A')
                            and not item['risks'])
    auction_rows=[i for i in items if i['quote_valid']] if auction else []
    auction_rows.sort(key=lambda i:(not i['monitor_candidate'],bool(i['risks']),-(i['price_attack_score'] or 0),i['code']))
    model=dict(version=VERSION,day=now.date().isoformat(),previous_close_asof=previous_day,background_asof=day,
               observed_at=observed_at,stage=session,price_judged_count=sum(i['quote_valid'] for i in items),
               structure_judged_count=sum(i['quote_valid'] and i['price_basis_valid'] and not i.get('partial_history') for i in items),
               states=dict(Counter(i['label'] for i in items)),auction_rows=auction_rows,
               auction_candidate_count=sum(i['monitor_candidate'] for i in auction_rows),
               note='前一完成日及真实收盘留档衔接当日报价；竞价价格判断自9:15开始，量价确认使用正式成交证据')
    snap['session_context']=model
    return model
