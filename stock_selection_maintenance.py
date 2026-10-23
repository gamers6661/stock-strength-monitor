"""独立服务盘后补齐日级资金与证券状态，不依赖编辑器会话。"""
import json
from datetime import datetime
import config
import stock_selection as S
import fund_history


def publish_and_validate():
    import stock_selection_validation as validation
    import stock_activity
    model=S.refresh_projection()
    source=stock_activity.live_view(json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8')))
    validation.archive_metadata(source)
    report=validation.forward()
    return dict(published=model['result_version'],mature=report['mature'],awaiting=report['awaiting'],pending_days=len(report['pending_decisions']))


def fetch_halted_dates(code,start,end):
    import sys,socket
    sys.path.insert(0,str(S.folder()/'vendor'))
    import baostock as bs
    old_timeout=socket.getdefaulttimeout();socket.setdefaulttimeout(20)
    expected=('sh.' if code.startswith('6') else 'sz.')+code
    try:
        login=bs.login()
        if login.error_code!='0':raise ValueError('证券状态源登录失败')
        query=bs.query_history_k_data_plus(expected,'date,code,volume,tradestatus',start_date=start,end_date=end,frequency='d',adjustflag='3')
        if query.error_code!='0':raise ValueError('证券状态查询失败 '+query.error_code)
        halted=set()
        while query.next():
            row=dict(zip(query.fields,query.get_row_data()))
            if row.get('code')!=expected or not start<=row.get('date','')<=end:raise ValueError('停牌响应代码或日期不匹配')
            if row.get('tradestatus')=='0' and (row['volume']=='' or float(row['volume'])==0):halted.add(row['date'])
        return halted
    finally:
        bs.logout();socket.setdefaulttimeout(old_timeout)


def refresh_gap_proofs(snap,histories,calendar,budget=30):
    import time
    if len(calendar)<S.R['min_bars']:return dict(updated=0,pending=[],reason='市场日期不足')
    day=calendar[-1];expected=calendar[-S.R['min_bars']:];proofs=S.read('history_gap_verification.json')
    master=snap.get('_security_master') or {};started=time.monotonic();updated=0;pending=[]
    for code in S.unique_rows(snap):
        history=histories.get(code,[]);clean,_=S.clean_bars(history,calendar,day)
        if clean or proofs.get(code,{}).get('asof')==day:continue
        bydate={b['date']:b for b in history}
        missing=[d for d in expected if d not in bydate or not S.intraday._valid_historical_price_bar(bydate[d]) or not S.number(bydate[d].get('volume')) or bydate[d]['volume']<=0]
        if not missing:continue
        old=proofs.get(code,{})
        ipo=master.get(code,{}).get('ipoDate') or old.get('ipo_date')
        needed={d for d in missing if not ipo or d>=ipo}
        known=set(old.get('halted_dates',[]));checked=old.get('checked_at');source=old.get('source')
        if not needed.issubset(known):
            if time.monotonic()-started>=budget:
                pending.append(dict(code=code,reason='停牌核验预算结束'));continue
            try:
                known.update(fetch_halted_dates(code,expected[0],day));checked=str(datetime.now());source='BaoStock 日线 tradestatus / volume'
            except Exception as exc:
                pending.append(dict(code=code,reason=type(exc).__name__+': '+str(exc)));continue
        if not needed.issubset(known):
            pending.append(dict(code=code,reason='缺口未被原始停牌状态证实',dates=sorted(needed-known)));continue
        proofs[code]=dict(asof=day,ipo_date=ipo,source=source or 'BaoStock 证券主表 ipoDate',checked_at=checked or (S.read('security_master.json').get('observed_at')),
            derived_at=str(datetime.now()),halted_dates=sorted(known&set(expected)),missing_dates=[d for d in missing if ipo and d<ipo],
            rows=sum(d in bydate for d in expected))
        updated+=1
    config.atomic_write_text(S.folder()/'history_gap_verification.json',json.dumps(proofs,ensure_ascii=False))
    report=dict(day=day,updated=updated,pending=pending,seconds=round(time.monotonic()-started,3))
    config.atomic_write_text(S.folder()/'history_gap_maintenance.json',json.dumps(report,ensure_ascii=False));return report


def maintain():
    snap=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
    master=S.read('security_master.json')
    # 证券状态每个自然周更新一次，失败保留上次已验证数据。
    at=S.parse_at(master.get('observed_at'))
    if not at or (datetime.now()-at).days>=7:
        import sys,socket
        sys.path.insert(0,str(S.folder()/'vendor'))
        import baostock as bs
        socket.setdefaulttimeout(20)
        try:
            bs.login();query=bs.query_stock_basic();stocks={}
            while query.error_code=='0' and query.next():
                row=dict(zip(query.fields,query.get_row_data()))
                if row.get('type')=='1':stocks[row['code'].split('.')[-1]]=row
            if len(stocks)>=3000:
                master=dict(source='BaoStock query_stock_basic',observed_at=str(datetime.now()),stocks=stocks)
                config.atomic_write_text(S.folder()/'security_master.json',json.dumps(master,ensure_ascii=False))
        finally:bs.logout()
    snap=dict(snap,_security_master=master.get('stocks',{}),_universe_at=str(datetime.now().date()))
    rows=S.unique_rows(snap);histories,calendar=S.inputs(snap)
    quality=refresh_gap_proofs(snap,histories,calendar)
    from stock_selection_calendar import refresh_calendar
    try:refresh_calendar()
    except Exception as exc:print(json.dumps(dict(calendar_pending=str(exc)),ensure_ascii=False))
    initial=publish_and_validate()
    print(json.dumps(dict(history_quality=quality,validation=initial),ensure_ascii=False))
    result=fund_history.refresh(list(rows),calendar,workers=8,deadline=180)
    config.atomic_write_text(S.folder()/'fund_maintenance.json',json.dumps(result,ensure_ascii=False))
    print(json.dumps(result,ensure_ascii=False))
    import stock_selection_intraday
    history=stock_selection_intraday.update_history(calendar)
    published=publish_and_validate()
    print(json.dumps(dict(same_time_history=history,validation=published),ensure_ascii=False))


if __name__=='__main__':maintain()
