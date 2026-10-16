import sys,json,hashlib,csv,io
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen,Request
from urllib.parse import urlencode
sys.path.insert(0,str(Path.cwd()))
import config,market_strength as M,ui_payload
OUT=Path(__file__).parent;BASE=OUT.parent/'baseline'
def digest(x):return hashlib.sha256(json.dumps(json.loads(json.dumps(x)),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def frozen():
    raw=(BASE/'frozen_complete_inputs.json').read_bytes();f=json.loads(raw)
    s=json.loads((BASE/'cache/snapshot.json').read_text('utf8'));old=json.loads((OUT.parent/'comparison.json').read_text('utf8'))
    members=digest([b['member_codes'] for b in s['board_catalog']]);indices=digest([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']])
    M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']));M.validate(s)
    rows=s['stocks']+s['coverage_catalog']
    assert all(digest(r['market_strength'])==digest(old['stocks'][r['code']]['new']) for r in rows)
    assert all(digest(b['market_strength'])==digest(old['boards'][b['id']]) for b in s['board_catalog'])
    assert members==digest([b['member_codes'] for b in s['board_catalog']])
    assert indices==digest([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']])
    assert raw==(BASE/'frozen_complete_inputs.json').read_bytes()
    assert config.ROOT.joinpath('config.py').read_bytes()==(OUT/'baseline/config.py').read_bytes()
    (OUT/'frozen_verification.json').write_text(json.dumps(dict(stocks=len(rows),boards=len(s['board_catalog']),models_equal=True,inputs_unchanged=True,members_unchanged=True,indices_unchanged=True,parameters_unchanged=True,input_sha256=hashlib.sha256(raw).hexdigest()),indent=2),'utf8')
    print('Frozen: all stock/board models unchanged; raw inputs, members, parameters unchanged.',flush=True)
def live():
    base='http://127.0.0.1:8848'
    def get(path):return urlopen(base+path,timeout=90).read()
    status=json.loads(get('/__status'));assert status['phase']=='ready' and status['last_publish_ok'] and status['last_scan_ok']
    assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']==M.IMPLEMENTATION_HASH
    html=get('/dashboard.html').decode('utf8');packet,_=json.JSONDecoder().raw_decode(html.split('var DATA = ',1)[1].lstrip());brief=ui_payload.unpack(packet);token=brief['ui_generation']
    assert token==status['ui_generation'];full=ui_payload.full(token);M.validate(full)
    by={r['code']:r for r in full['stocks']+full['coverage_catalog']};boards={b['id']:b for b in full['board_catalog']}
    def export(payload):return urlopen(Request(base+'/__ui/export',data=json.dumps(dict(version=token,**payload)).encode(),headers={'Content-Type':'application/json'}),timeout=90).read()
    focus=full['market_strength']['stocks']['focus'];stock=export(dict(codes=focus,contexts={}));(OUT/'stocks.csv').write_bytes(stock)
    records=list(csv.DictReader(io.StringIO(stock.decode('utf-8-sig'))));assert [r['代码'] for r in records]==focus
    for r in records:assert json.loads(r['完整模型依据'])==by[r['代码']]['market_strength'] and r['UI版本']==token
    board_counts={}
    for kind in ('industry','theme'):
        ids=[i for i in full['market_strength']['boards']['sorts']['combined'] if i in full['market_strength']['boards']['focus'] and boards[i]['type']==kind]
        before=export(dict(kind='board',ids=ids));(OUT/(kind+'.csv')).write_bytes(before)
        for identity in ids[:3]:
            detail=json.loads(get('/__ui/detail?'+urlencode(dict(version=token,kind='board',id=identity))))
            assert detail['item']['market_strength']==boards[identity]['market_strength']
            assert before==export(dict(kind='board',ids=ids))
        recs=list(csv.DictReader(io.StringIO(before.decode('utf-8-sig'))));assert [r['ID'] for r in recs]==ids
        for r in recs:assert json.loads(r['完整模型依据'])==boards[r['ID']]['market_strength'] and r['UI版本']==token
        board_counts[kind]=len(recs)
    (OUT/'live_verification.json').write_text(json.dumps(dict(pid=status['pid'],version=M.VERSION,implementation_hash=M.IMPLEMENTATION_HASH,data_version=status['data_version'],ui_generation=token,counts=full['market_strength']['counts'],board_counts=full['market_strength']['board_counts'],export_counts=board_counts,stock_export_rows=len(records),source_at=full['quote_capture_at'],detail_order_invariant=True),ensure_ascii=False,indent=2),'utf8')
    (OUT/'post_publish_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),'utf8')
    print('HTTP: same generation full exports verified:',len(records),board_counts,flush=True)
def boundaries():
    from test_market_strength_rework import TimeProtection
    t=TimeProtection();results={}
    cases=[('close_previous','2026-10-12 15:00:00','已收盘',datetime(2026,10,13,16),True,False),
           ('close_future','2026-10-14 15:00:00','已收盘',datetime(2026,10,13,16),True,False),
           ('close_morning','2026-10-13 10:00:00','已收盘',datetime(2026,10,13,16),True,False),
           ('lunch_1230','2026-10-13 12:30:00','午间休市',datetime(2026,10,13,12,30),False,False),
           ('close_today','2026-10-13 15:00:00','已收盘',datetime(2026,10,13,20),True,True),
           ('lunch_1131','2026-10-13 11:31:11','午间休市',datetime(2026,10,13,12,30),False,True),
           ('afternoon','2026-10-13 13:05:00','午盘',datetime(2026,10,13,13,5),False,True)]
    for name,at,session,now,verified,valid in cases:
        s=t.evaluate(at,session,now,str(now) if verified else None);m=s['stocks'][0]['market_strength'];count=s['market_strength']['counts']['focus']
        assert count==(10 if valid else 0)
        results[name]=dict(quote_at=at,now=str(now),trend=m['trend_score'],emotion=m['emotion_score'],focus=count,reasons=m['data_reasons'],mode=m['mode'])
    (OUT/'time_boundaries.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    print('Reproduced all reported illegal timestamps plus valid controls; fixed.',flush=True)
if __name__=='__main__':
    if 'frozen' in sys.argv:frozen()
    elif 'boundaries' in sys.argv:boundaries()
    else:live()
