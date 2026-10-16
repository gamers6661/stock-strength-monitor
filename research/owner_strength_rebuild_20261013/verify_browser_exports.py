import csv,hashlib,io,json,sys
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path.cwd()))
import ui_payload,market_strength as M
O=Path(__file__).parent;v=json.loads((O/'live_verification.json').read_text('utf8'))
token=v['ui_generation'];s=ui_payload.full(token);M.validate(s)
raw=(O/'browser-members.csv').read_bytes()
exported=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
codes=[r['代码'] for r in exported];by={r['code']:r for r in s['stocks']+s['coverage_catalog']}
board=next(b for b in s['board_catalog'] if b['name']=='出版' and b['type']=='industry')
assert set(codes)==set(board['member_codes'])&set(by)
assert raw==ui_payload.export_csv(token,codes,{})
for row in exported:
    m=by[row['代码']]['market_strength']
    assert json.loads(row['完整模型依据'])==m
    assert row['UI版本']==token
board_results={}
for kind in ('industry','theme'):
    mapping={b['id']:b for b in s['board_catalog']}
    ids=[i for i in s['market_strength']['boards']['sorts']['trend'] if i in s['market_strength']['boards']['focus'] and mapping[i]['type']==kind]
    req=Request('http://127.0.0.1:8848/__ui/export',data=json.dumps(dict(version=token,kind='board',ids=ids)).encode(),headers={'Content-Type':'application/json'},method='POST')
    content=urlopen(req,timeout=60).read()
    assert content==ui_payload.export_board_csv(token,ids)
    rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    for r in rows:assert json.loads(r['完整模型依据'])==mapping[r['ID']]['market_strength']
    (O/(kind+'.csv')).write_bytes(content)
    board_results[kind]=dict(rows=len(rows),sha256=hashlib.sha256(content).hexdigest())
proof=json.loads((O/'browser_proof.json').read_text('utf8'))
assert proof['sourceGeneration']==token
assert codes==proof['memberCodes']
for label,key,order in [('pullbackIds','pullback','trend'),('emotionIds','emotion','emotion'),('dayAttackIds','day_attack','day_attack')]:
    lists=s['market_strength']['stocks']
    expected=lists['day_attack'] if order=='day_attack' else [c for c in lists['sorts'][order] if c in lists[key]]
    assert proof[label]==expected[:60],label
assert proof['emotionSort']=='emotion'
result=dict(ui_generation=token,member_rows=len(codes),all_confirmed_members=True,browser_csv_equal_http=True,
            browser_lists_equal_backend=True,board_exports=board_results)
(O/'browser_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(result)
