from pathlib import Path
root=Path(r'D:\股票强势监测')
def edit(name,old,new):
 p=root/name
 text=p.read_text(encoding='utf-8')
 assert text.count(old)==1,(name,'count',text.count(old),old[:90])
 p.write_text(text.replace(old,new),encoding='utf-8')
 print('EDIT',name)
edit('stock_activity.py',"""    if not formal and (at<=original or (now-at).total_seconds()>RULES['quote_age_max']):return snap
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    quotes={c:q for c,q in (record.get('quotes') or {}).items() if c in rows}
    fallback=formal and at<=original
""","""    if not formal and ((now-at).total_seconds()>RULES['quote_age_max']
                       or at<original and (original-at).total_seconds()>15):return snap
    rows={r['code']:r for r in snap.get('stocks',[])+snap.get('coverage_catalog',[])}
    quotes={c:q for c,q in (record.get('quotes') or {}).items() if c in rows}
    # The shared snapshot may have been generated seconds after a verified
    # independent acquisition but may lack its raw-price provenance fields.
    # Recover only genuinely comparable same-day per-stock quotes; never
    # overwrite a newer, fully sourced snapshot with an older quote.
    if not formal and at<=original:
        def near_sourced(c,q):
            row=rows[c]
            source,existing=stamp(q.get('quote_at')),stamp(row.get('quote_at'))
            return bool(source and existing and source.date()==original.date()
                and -10 <= (source-existing).total_seconds() <= 15
                and q.get('price_basis')=='raw'
                and q.get('last_close_semantics')=='previous_trade_day_raw_close'
                and q.get('price_basis_source')
                and number(q.get('last_close')) and number(row.get('last_close'))
                and abs(q['last_close']-row['last_close'])<=.005
                and (not row.get('last_close_semantics') or
                     row.get('last_close_semantics')==q.get('last_close_semantics'))
                and (not row.get('price_basis') or row.get('price_basis')==q.get('price_basis'))
                and (not row.get('price_basis_source') or row.get('price_basis_source')==q.get('price_basis_source'))
                and (not row.get('price_basis_source') or source>=existing))
        quotes={c:q for c,q in quotes.items() if near_sourced(c,q)}
        if len(quotes)<len(rows)*RULES['coverage_min']:return snap
    fallback=formal and at<=original
""")
edit('stock_activity.py',"""    captured=max(original,at) if fallback else at
""","""    captured=max(original,at) if fallback or at<=original else at
""")
edit('stock_activity_engine.py',"""    broken=p['price']<identity['support_price']
    loss=lead<R['identity_lead_floor_pp'] and attention is not None and attention<R['identity_attention_min']
    no_support=""","""    broken=p['price']<identity['support_price']
    # Large, persistent giveback of an established impulse can invalidate
    # leadership even when heavy selling leaves turnover/attention elevated.
    confirmed_peaks=[e.get('peak',0.) for e in events
                     if e['id'] in identity.get('event_ids',[])
                     and confirmed(e,'holding')]
    peak=max(confirmed_peaks+[identity.get('peak_price',0.),p['price']])
    identity['peak_price']=peak
    atr=next((e.get('atr') for e in reversed(events)
              if e['id'] in identity.get('event_ids',[]) and e.get('atr',0)>0),None)
    strong_giveback=bool(atr and peak-p['price']>=max(2.*atr,.08*peak)
                         and lead<0 and p['price']<peak-.5*atr)
    loss=lead<R['identity_lead_floor_pp'] and attention is not None and attention<R['identity_attention_min']
    no_support=""")
edit('stock_activity_engine.py',"""    if fresh and (broken or loss or no_support):
""","""    if fresh and (broken or loss or no_support or strong_giveback):
""")
edit('stock_activity_engine.py',"""        reason='锁定结构失守' if broken else '领先优势与关注度同时丧失' if loss else '当前及历史超额均不再支持既有核心身份'
""","""        reason=('锁定结构失守' if broken else '已确认进攻成果持续大幅回吐' if strong_giveback
                else '领先优势与关注度同时丧失' if loss else '当前及历史超额均不再支持既有核心身份')
""")
print('ALL_PATCHES_APPLIED')
