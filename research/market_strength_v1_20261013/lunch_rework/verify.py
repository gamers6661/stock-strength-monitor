import sys,json,copy,hashlib,csv,io
from pathlib import Path
from datetime import datetime
from urllib.request import Request,urlopen
from urllib.parse import urlencode
sys.path.insert(0,str(Path.cwd()))
import market_strength as M,config,ui_payload
O=Path(__file__).parent;B=O.parent/'baseline'
def digest(x):return hashlib.sha256(json.dumps(json.loads(json.dumps(x)),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def scenarios():
    raw=(B/'frozen_complete_inputs.json').read_bytes();f=json.loads(raw);s=json.loads((B/'cache/snapshot.json').read_text('utf8'));compare=json.loads((O.parent/'comparison.json').read_text('utf8'))
    M.attach(s,f['quotes'],f['pool'],f['histories'],f['calendar'],now=datetime.fromisoformat(f['now']));M.validate(s)
    assert all(digest(r['market_strength'])==digest(compare['stocks'][r['code']]['new']) for r in s['stocks']+s['coverage_catalog'])
    assert all(digest(b['market_strength'])==digest(compare['boards'][b['id']]) for b in s['board_catalog'])
    previous=copy.deepcopy(s);q=copy.deepcopy(f['quotes'])
    for quote in q.values():quote.update(quote_at='2026-10-13 12:30:00',ts='20261013123000',price=1.,change_pct=-90.)
    original=digest(q);s['session']='午间休市';M.attach(s,q,f['pool'],f['histories'],f['calendar'],now=datetime(2026,10,13,12,45),previous=previous);M.validate(s)
    assert digest(q)==original
    for key in ('stocks','boards','counts','board_counts'):assert s['market_strength'][key]==previous['market_strength'][key]
    retained=copy.deepcopy(s);M.attach(s,{},f['pool'],f['histories'],f['calendar'],now=datetime(2026,10,13,12,59),previous=retained);M.validate(s)
    assert s['market_strength']['stocks']==previous['market_strength']['stocks'];assert s['market_strength']['boards']==previous['market_strength']['boards']
    results=dict(frozen_models_equal=True,config_unchanged=config.ROOT.joinpath('config.py').read_bytes()==(O/'baseline/config.py').read_bytes(),raw_input_unchanged=raw==(B/'frozen_complete_inputs.json').read_bytes(),morning=previous['market_strength']['counts'],lunch=s['market_strength']['counts'],lunch_boards=s['market_strength']['board_counts'],source_at=s['market_strength']['reference_source_at'],evaluation_at=s['market_strength']['reference_evaluation_at'],repeated_refresh_same=True)
    noon=copy.deepcopy(s);s['session']='午盘';newquotes=copy.deepcopy(f['quotes'])
    for quote in newquotes.values():quote.update(quote_at='2026-10-13 13:05:00',ts='20261013130500')
    M.attach(s,newquotes,f['pool'],f['histories'],f['calendar'],now=datetime(2026,10,13,13,5),previous=noon);M.validate(s)
    assert all(r['market_strength'].get('quote_at')=='2026-10-13 13:05:00' for r in s['stocks']+s['coverage_catalog'] if r['market_strength']['focus'])
    assert '午休' not in s['market_strength']['mode'];results['afternoon_valid_replaces']=s['market_strength']['counts']
    s['session']='午盘';M.attach(s,{},f['pool'],f['histories'],f['calendar'],now=datetime(2026,10,13,13,5),previous=noon);M.validate(s)
    assert s['market_strength']['counts']['focus']==s['market_strength']['board_counts']['focus']==0
    results['afternoon_missing_focus']=0
    (O/'state_transitions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    # A clearly labelled test fixture only. Do not activate its immutable store.
    noon['runtime_contract']=dict(code_market_strength_version=M.VERSION,code_market_strength_hash=M.IMPLEMENTATION_HASH)
    template=(config.ROOT/'dashboard_template.html').read_text('utf8')
    for marker,name in [('/*__RADAR_SCRIPT__*/','radar_ui.js'),('/*__CSV_SCRIPT__*/','csv_export.js'),('/*__UI_SCRIPT__*/','ui_client.js')]:template=template.replace(marker,(config.ROOT/name).read_text('utf8'))
    template=template.replace('<body>','<body><div style="padding:12px;background:#fff0c2;color:#222">午休衔接验收 · 保留原11:31批次 · 非当前实盘发布</div>')
    template=template.replace('installLazyDetails();','updateDashboardData=function(){return Promise.resolve();};installLazyDetails();')
    packet,token=ui_payload.prepare(noon,template,config.ROOT/'dashboard.html')
    (O/'lunch_fixture.html').write_text(template.replace('/*__DATA__*/null',config.script_json(packet)),'utf8')
    (O/'fixture_generation.json').write_text(json.dumps(dict(generation=token,source_at=noon['market_strength']['reference_source_at'],mode=noon['market_strength']['mode'],counts=noon['market_strength']['counts']),ensure_ascii=False,indent=2),'utf8')
    (O/'browser').mkdir(exist_ok=True)
    script=(O.parent/'rework_3/browser_check.js').read_text('utf8').replace("rework_3';","lunch_rework/browser';").replace('http://127.0.0.1:8848/dashboard.html','http://127.0.0.1:8848/research/market_strength_v1_20261013/lunch_rework/lunch_fixture.html')
    (O/'browser_check.js').write_text(script,'utf8')
    print('Frozen and transitions verified: morning -> invalid/missing/repeated lunch retained; afternoon replaced or empty.',flush=True)
def exports(token,out):
    full=ui_payload.full(token);M.validate(full);by={r['code']:r for r in full['stocks']+full['coverage_catalog']};boards={b['id']:b for b in full['board_catalog']}
    payloads={kind:dict(kind='board',ids=[i for i in full['market_strength']['boards']['sorts']['combined'] if i in full['market_strength']['boards']['focus'] and boards[i]['type']==kind]) for kind in ('industry','theme')}
    payloads['stocks']=dict(codes=full['market_strength']['stocks']['focus'],contexts={})
    for kind,payload in payloads.items():
        raw=urlopen(Request('http://127.0.0.1:8848/__ui/export',data=json.dumps(dict(version=token,**payload)).encode(),headers={'Content-Type':'application/json'}),timeout=90).read();(out/(kind+'.csv')).write_bytes(raw)
        records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        for row in records:
            expected=by[row['代码']]['market_strength'] if kind=='stocks' else boards[row['ID']]['market_strength']
            assert json.loads(row['完整模型依据'])==expected and row['UI版本']==token
    return full
def live():
    status=json.load(urlopen('http://127.0.0.1:8848/__status'));assert status['phase']=='ready' and not status['scan_active'] and status['last_publish_ok']
    assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']==M.IMPLEMENTATION_HASH
    full=exports(status['ui_generation'],O)
    (O/'post_publish_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),'utf8')
    (O/'live_verification.json').write_text(json.dumps(dict(pid=status['pid'],ui_generation=status['ui_generation'],implementation_hash=M.IMPLEMENTATION_HASH,counts=full['market_strength']['counts'],board_counts=full['market_strength']['board_counts'],source_at=full['quote_capture_at']),ensure_ascii=False,indent=2),'utf8')
    print('Runtime/snapshot/local hash, live CSVs and full reference fixture HTTP CSVs agree.',flush=True)
def fixture_check():
    token=json.loads((O/'fixture_generation.json').read_text('utf8'))['generation']
    full=ui_payload.full(token);M.validate(full)
    models={r['code']:r['market_strength'] for r in full['stocks']+full['coverage_catalog']}
    boards={b['id']:b['market_strength'] for b in full['board_catalog']}
    result,_=json.JSONDecoder().raw_decode((O/'browser/browser_check.txt').read_text('utf8').split('### Result',1)[1].lstrip())
    assert result['generation']==token
    proof=dict(generation=token,mode=full['market_strength']['mode'],source_at=full['market_strength']['reference_source_at'],members=result['members'],exports={})
    for kind in ('industry','theme'):
        raw=(O/'browser'/(kind+'.csv')).read_bytes()
        assert all(raw==(O/'browser'/(kind+'-'+suffix+'.csv')).read_bytes() for suffix in ('before','one','many'))
        records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        for row in records:assert json.loads(row['完整模型依据'])==boards[row['ID']] and '午休参考' in row['完整模型依据']
        proof['exports'][kind]=dict(rows=len(records),three_browser_orders_byte_equal=True,full_backend_objects_equal=True)
    raw=(O/'browser/stocks.csv').read_bytes();assert raw==(O/'browser/stocks-browser.csv').read_bytes()
    records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    assert [r['代码'] for r in records]==full['market_strength']['stocks']['focus']
    for row in records:assert json.loads(row['完整模型依据'])==models[row['代码']] and '午休参考' in row['完整模型依据']
    proof['exports']['stocks']=dict(rows=len(records),browser_http_byte_equal=True,full_backend_objects_equal=True)
    original=json.loads((O.parent/'comparison.json').read_text('utf8'))
    unchanged=0
    for code,model in models.items():
        old=original['stocks'][code]['new']
        if old['trend_score'] is not None or old['emotion_score'] is not None:
            normalized=copy.deepcopy(model);normalized.pop('reference_source_at',None);normalized['mode']=old['mode']
            assert normalized==old,(code,'reference evidence changed')
            unchanged+=1
    for identity,model in boards.items():
        normalized=copy.deepcopy(model);normalized.pop('reference_source_at',None);normalized['mode']=original['boards'][identity]['mode']
        assert normalized==original['boards'][identity],identity
    proof['effective_stock_models_unchanged']=unchanged
    proof['all_board_models_unchanged']=len(boards)
    (O/'fixture_verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),'utf8')
    print('Reference page/members/stock/industry/theme CSVs use the same original morning batch.',flush=True)
if __name__=='__main__':
    if 'scenarios' in sys.argv:scenarios()
    elif 'fixture' in sys.argv:fixture_check()
    else:live()
