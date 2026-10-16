"""Independent acceptance evidence; production files and operator evidence stay unchanged."""
import copy
import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import market_strength as M
import config
import ui_payload
from test_market_strength import fixture, run

OUT = ROOT / 'research/market_strength_v1_20261013'
BASE = OUT / 'baseline'
evidence = {}

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def digest(value):
    # JSON changes integer object keys to strings; normalize before ordering keys.
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf8'))
bad = [name for name, expected in manifest.items()
       if not (BASE / name).exists() or sha(BASE / name) != expected]
changed = json.loads((OUT / 'changed_files.json').read_text(encoding='utf8'))
drift = [r['file'] for r in changed if sha(ROOT / r['file']) != r['sha256']]
evidence['files'] = dict(backup_count=len(manifest), backup_mismatches=bad, delivered_source_drift=drift,
                         instruction_hash=sha(OUT / '负责人执行指令.md'))
print('FILES', evidence['files'], flush=True)

f = json.loads((BASE / 'frozen_complete_inputs.json').read_text(encoding='utf8'))
input_before = {k: digest(f[k]) for k in ('quotes', 'histories', 'pool', 'calendar', 'boards')}
acquisition = json.loads((BASE / 'raw_acquisition_113111.json').read_text(encoding='utf8'))
raw_differences = [r[0] for r in acquisition['rows']
                   if any(f['quotes'][r[0]].get(k) != v for k, v in zip(acquisition['fields'][1:], r[1:]))]
s = json.loads((BASE / 'cache/snapshot.json').read_text(encoding='utf8'))
membership_before = digest([b['member_codes'] for b in s['board_catalog']])
index_before = digest([{k: v for k, v in b.items() if k.startswith('index_')} for b in s['board_catalog']])
M.attach(s, f['quotes'], f['pool'], f['histories'], f['calendar'], now=datetime.fromisoformat(f['now']))
M.validate(s)
reported = json.loads((OUT / 'comparison.json').read_text(encoding='utf8'))
rows = {r['code']: r for r in s['stocks'] + s['coverage_catalog']}
stock_diffs = [c for c, r in rows.items() if digest(r['market_strength']) != digest(reported['stocks'][c]['new'])]
board_diffs = [b['id'] for b in s['board_catalog'] if digest(b['market_strength']) != digest(reported['boards'][b['id']])]
evidence['frozen_replay'] = dict(now=f['now'], stock_count=len(rows), stock_differences=stock_diffs,
    serialization='Compare canonical JSON; integer dictionary keys are strings on disk',
    raw_acquisition_differences=raw_differences,acquisition_clock_match=acquisition['captured_at']==f['now'],
    board_differences=board_diffs, counts=s['market_strength']['counts'], board_counts=s['market_strength']['board_counts'],
    input_changed=[k for k in input_before if digest(f[k]) != input_before[k]],
    members_unchanged=membership_before == digest([b['member_codes'] for b in s['board_catalog']]),
    index_unchanged=index_before == digest([{k:v for k,v in b.items() if k.startswith('index_')} for b in s['board_catalog']]))
print('FROZEN', {k:v for k,v in evidence['frozen_replay'].items() if k not in ('stock_differences','board_differences')},
      'stock_differences',len(stock_diffs),'board_differences',len(board_diffs), flush=True)
del s, rows, reported, f

def case(at, session, now, verified=False):
    f = fixture()
    s, qs, pool, hs, cal, original_now = f
    s['session'] = session
    if verified:
        s['close_daily_verified_at'] = now.isoformat(sep=' ')
        # Include actual completed evaluation-day bars, so the repro does not rely on missing close history.
        for bars in hs.values():
            bars.append(dict(bars[-1],date=now.date().isoformat(),open=100.,high=110.,low=100.,close=110.))
        cal.append(now.date().isoformat())
    for q in qs.values():
        q.update(price=110., open=100., high=110., low=100., change_pct=10., quote_at=at)
    M.attach(s, qs, pool, hs, cal, now=now)
    m = s['stocks'][0]['market_strength']
    return dict(quote_at=at, now=str(now), verified=verified, focus=s['market_strength']['counts']['focus'],
                trend=m['trend_score'], emotion=m['emotion_score'], mode=m['mode'], reasons=m['data_reasons'])

evidence['time_boundaries'] = {
    'lunch_1230_quote': case('2026-10-13 12:30:00', '午间休市', datetime(2026,10,13,12,30)),
    'formal_close_previous_day': case('2026-10-12 15:00:00', '已收盘', datetime(2026,10,13,16), True),
    'formal_close_morning_only': case('2026-10-13 10:00:00', '已收盘', datetime(2026,10,13,16), True),
    'formal_close_future': case('2026-10-14 15:00:00', '已收盘', datetime(2026,10,13,16), True),
    'formal_close_today_valid': case('2026-10-13 15:00:00', '已收盘', datetime(2026,10,13,16), True),
    'lunch_actual_1131_quote': case('2026-10-13 11:31:11', '午间休市', datetime(2026,10,13,12,30)),
}
print('BOUNDARIES', evidence['time_boundaries'], flush=True)

base_url='http://127.0.0.1:8848'
def get(path):
    return urlopen(base_url+path, timeout=45).read()
status = json.loads(get('/__status'))
page = get('/dashboard.html').decode('utf8')
packet, _ = json.JSONDecoder().raw_decode(page.split('var DATA = ',1)[1].lstrip())
brief = ui_payload.unpack(packet)
token = brief['ui_generation']
snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf8'))
assert brief['market_strength'] == snapshot['market_strength']
by_code = {r['code']: r for r in snapshot['stocks']+snapshot['coverage_catalog']}
by_board = {r['id']: r for r in snapshot['board_catalog']}
focus = snapshot['market_strength']['stocks']['focus']
codes = [focus[0]] + [c for c in focus if by_code[c]['market_strength']['emotion_strong'] and not by_code[c]['market_strength']['trend_strong']][:1]
matches = []
for kind, identities, source in [('stock',codes,by_code),('board',snapshot['market_strength']['boards']['focus'][:2],by_board)]:
    for identity in identities:
        detail = json.loads(get('/__ui/detail?'+urlencode(dict(version=token,kind=kind,id=identity))))
        matches.append(dict(kind=kind,id=identity,match=detail['item']['market_strength']==source[identity]['market_strength']))
request = Request(base_url+'/__ui/export',data=json.dumps(dict(version=token,codes=focus,contexts={})).encode(),
                  headers={'Content-Type':'application/json'},method='POST')
raw = urlopen(request,timeout=45).read()
exported = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
stock_csv_errors = [r['代码'] for r in exported if json.loads(r['完整模型依据']) != by_code[r['代码']]['market_strength']]
board_download = (Path.home() / 'Downloads') / ('板块强度_'+token+'.csv')
board_export = list(csv.DictReader(io.StringIO(board_download.read_text(encoding='utf-8-sig')))) if board_download.exists() else []
board_csv_missing = [dict(id=r['ID'],missing=[k for k in ('trend_parts_by_period','emotion_parts','expected','history_trend')
                      if k not in json.loads(r['完整模型依据'])],full_match=json.loads(r['完整模型依据'])==by_board[r['ID']]['market_strength']) for r in board_export]
evidence['live'] = dict(now=str(datetime.now()),pid=status['pid'],phase=status['phase'],scan_active=status['scan_active'],
    versions_match=status['code_market_strength_version']==status['snapshot_market_strength_version']==M.VERSION,
    hashes_match=status['code_market_strength_hash']==status['snapshot_market_strength_hash']==M.IMPLEMENTATION_HASH,
    data_version=status['data_version'],ui_generation=token,mode=brief['market_strength']['mode'],
    counts=brief['market_strength']['counts'],board_counts=brief['market_strength']['board_counts'],details=matches,
    stock_export_count=len(exported),stock_export_order_match=[r['代码'] for r in exported]==focus,stock_export_errors=stock_csv_errors,
    board_csv_rows=len(board_export),board_csv_fields=board_csv_missing)
print('LIVE', evidence['live'], flush=True)
(OUT / '负责人独立验收证据.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2),encoding='utf8')
