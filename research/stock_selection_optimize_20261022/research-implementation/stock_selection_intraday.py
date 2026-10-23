"""Same-source, same-clock cumulative volume. Observational only; never a score gate."""
import gzip
import json
import sqlite3
from datetime import datetime
from statistics import median
from pathlib import Path

import config
from stock_selection_rules import RULES as R


def path():
    return config.CACHE_DIR/'stock_selection_v3'/'intraday.db'


def update_history(calendar,now=None):
    import stock_activity as A
    import intraday
    now=now or datetime.now()
    days=[d for d in calendar if d<str(now.date()) or d==str(now.date()) and now.hour>=16][-R['same_time_reference_days']:]
    folder=path();folder.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(folder)
    db.execute('CREATE TABLE IF NOT EXISTS volumes(day TEXT,second INTEGER,code TEXT,volume REAL,PRIMARY KEY(day,second,code))')
    db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,size INTEGER,mtime INTEGER)')
    inserted=0;processed=[]
    try:
        for day in days:
            for parent in (intraday.HISTORY_DIR/'acquisitions',config.CACHE_DIR/'stock_activity_samples'/'acquisitions'):
                file=parent/(day+'.jsonl.gz')
                if not file.exists():continue
                stat=file.stat();key=(str(file.resolve()),stat.st_size,stat.st_mtime_ns)
                if db.execute('SELECT size,mtime FROM files WHERE path=?',(key[0],)).fetchone()==key[1:]:continue
                before=db.total_changes
                with gzip.open(file,'rt',encoding='utf8') as stream:
                    for line in stream:
                        record=json.loads(line);at=A.stamp(record.get('captured_at'))
                        if not at or str(at.date())!=day:continue
                        fields=record['fields'];quotes={r[0]:dict(zip(fields[1:],r[1:])) for r in record['rows']}
                        quotes={c:q for c,q in quotes.items() if q.get('price_basis')=='raw' and q.get('price_basis_source')=='tencent_realtime_quote'}
                        frame=A.valid_frame(quotes,at,record.get('session','连续竞价'))
                        rows=[]
                        for code,point in frame.items():
                            t=A.stamp(point['at']);volume=point.get('volume_shou')
                            if t and str(t.date())==day and A.number(volume) and volume>0:
                                rows.append((day,t.hour*3600+t.minute*60+t.second,code,volume))
                        db.executemany('INSERT OR IGNORE INTO volumes VALUES(?,?,?,?)',rows)
                inserted+=db.total_changes-before
                db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)',key);db.commit();processed.append(str(file))
    finally:db.close()
    return dict(days=days,inserted=inserted,processed=processed,source='腾讯累计成交量(手)')


def attach(model,source,calendar):
    import stock_selection as S
    rows=S.unique_rows(source);day=model['day']
    expected=[d for d in calendar if d<day][-R['same_time_reference_days']:]
    targets={}
    for code,item in model['items'].items():
        live=item['intraday'];at=S.parse_at(live.get('at'))
        live.update(volume_ratio_same_time=None,same_time_reference_volume=None,same_time_reference_samples=[],same_time_reference_days=0,same_time_expected_days=R['same_time_reference_days'])
        if live.get('available') and (rows[code].get('price_basis')!='raw' or rows[code].get('price_basis_source')!='tencent_realtime_quote'):
            live['same_time_volume_reason']='当前累计量来源待核验，不与腾讯历史混合比较'
            continue
        if live.get('available') and at and str(at.date())==day:
            targets[code]=at.hour*3600+at.minute*60+at.second
    references={}
    if targets and path().exists() and len(expected)==R['same_time_reference_days']:
        con=sqlite3.connect('file:'+path().as_posix()+'?mode=ro',uri=True)
        try:
            placeholders=','.join('?' for _ in expected);tolerance=R['same_time_tolerance_seconds']
            query='SELECT day,second,code,volume FROM volumes WHERE day IN ('+placeholders+') AND second BETWEEN ? AND ?'
            for d,second,code,volume in con.execute(query,expected+[min(targets.values())-tolerance,max(targets.values())+tolerance]):
                target=targets.get(code)
                if target is None or abs(second-target)>tolerance:continue
                key=(code,d);order=(abs(second-target),second)
                if key not in references or order<references[key][0]:references[key]=(order,volume,second)
        finally:con.close()
    for code in targets:
        live=model['items'][code]['intraday']
        samples=[(d,references[(code,d)][1],references[(code,d)][2]) for d in expected if (code,d) in references]
        live['same_time_reference_days']=len(samples)
        live['same_time_reference_samples']=samples
        volume=rows[code].get('volume_shou')
        if len(samples)==R['same_time_reference_days'] and S.number(volume) and volume>0:
            base=median(v for _,v,_ in samples)
            live.update(volume_ratio_same_time=volume/base,same_time_reference_volume=base,
                same_time_volume_reason='腾讯累计成交量(手)，最近5个完成交易日同源时点；仅供观察')
        else:
            live['same_time_volume_reason']='同源同时间量样本 '+str(len(samples))+'/'+str(R['same_time_reference_days'])+' 日，暂停量比判断'
    return model
