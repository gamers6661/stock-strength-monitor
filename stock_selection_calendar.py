"""Sourced exchange calendar; absent calendar never becomes inferred trading days."""
import json
from datetime import datetime,timedelta
import config

SOURCE='BaoStock query_trade_dates'


def path():return config.CACHE_DIR/'stock_selection_v3/trading_calendar.json'


def validate(record,start,end):
    if record.get('source')!=SOURCE:return []
    rows=record.get('days',{})
    current=datetime.fromisoformat(start).date();stop=datetime.fromisoformat(end).date()
    dates=[]
    while current<=stop:
        day=str(current)
        if rows.get(day) not in ('0','1'):return []
        if rows[day]=='1':dates.append(day)
        current+=timedelta(days=1)
    return dates


def load_calendar(start,end):
    try:record=json.loads(path().read_text(encoding='utf8'))
    except (OSError,ValueError):return []
    return validate(record,start,end)


def refresh_calendar(start=None,end=None):
    import sys,socket
    now=datetime.now();start=start or str(now.year-1)+'-01-01';end=end or str(now.date())
    if load_calendar(start,end):return dict(status='cached',start=start,end=end)
    sys.path.insert(0,str(path().parent/'vendor'))
    import baostock as bs
    old=socket.getdefaulttimeout();socket.setdefaulttimeout(20)
    try:
        if bs.login().error_code!='0':raise ValueError('交易日历登录失败')
        q=bs.query_trade_dates(start_date=start,end_date=end)
        if q.error_code!='0':raise ValueError('交易日历查询失败 '+q.error_code)
        rows={}
        while q.next():
            r=dict(zip(q.fields,q.get_row_data()));day=r.get('calendar_date')
            if not day or not start<=day<=end or day in rows or r.get('is_trading_day') not in ('0','1'):raise ValueError('交易日历响应无效')
            rows[day]=r['is_trading_day']
        if q.error_code!='0':raise ValueError('交易日历响应中断')
        record=dict(source=SOURCE,observed_at=str(now),days=rows)
        if not validate(record,start,end):raise ValueError('交易日历自然日覆盖不完整')
        path().parent.mkdir(parents=True,exist_ok=True)
        config.atomic_write_text(path(),json.dumps(record,ensure_ascii=False))
        return dict(status='updated',days=len(rows),start=start,end=end)
    finally:
        bs.logout();socket.setdefaulttimeout(old)


if __name__=='__main__':print(json.dumps(refresh_calendar(),ensure_ascii=False))
