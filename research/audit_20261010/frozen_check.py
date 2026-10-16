"""Full pipeline comparison on the same quotes/history; all writes use a copied cache."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import datafeed as df
import scoring
import strength
import board_trend
import board_quote
import intraday
import close_monitor
import trend_consolidation
import wyckoff_structure
import stock_strength
import session_context
import make_dashboard
import scan_cache

HERE = Path(__file__).resolve().parent
original = config.CACHE_DIR
snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
quotes = {r['code']: deepcopy(r) for r in snap['stocks']+snap['coverage_catalog']}
quote_fields = ('code','name','price','change_pct','open','high','low','last_close','limit_up','limit_down',
                'limit_pct','board_type','board_name','list_days','is_new','amount_wan','turnover_pct',
                'float_mcap_yi','ts','quote_at','volume_shou','amplitude_pct','vol_ratio','price_basis',
                'price_basis_source','last_close_semantics','total_mcap_yi')
quotes = {c: {k:r[k] for k in quote_fields if k in r} for c,r in quotes.items()}
pool_input = json.loads(config.POOL_CACHE.read_text(encoding='utf-8'))
board_quotes = {b['index_trend']['code']: b.get('index_quote') or {}
                for b in snap['board_catalog'] if b.get('index_trend')}
fixed = datetime.fromisoformat(snap['generated_at'])

class Clock(datetime):
    @classmethod
    def now(cls): return cls.fromtimestamp(fixed.timestamp())

# Reuse source-tagged official local histories; no invented bars or live requests.
input_file = ROOT/'research'/'performance_round2_20261010'/'board_inputs.json'
if not input_file.exists():
    inputs = {code: [name, board_trend.load(code)] for code, name in df.scan_ths_boards().items()}
    input_file.write_text(json.dumps(inputs, ensure_ascii=False), encoding='utf-8')
inputs = json.loads(input_file.read_text(encoding='utf-8'))
print('captured boards', len(inputs), flush=True)

def before(name):
    # .before is deliberately not an importable module suffix.
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader('before_'+name, str(HERE/(name+'.py.before')))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

old_strength, old_board, old_scoring = before('strength'), before('board_trend'), before('scoring')
old_scoring.strength = old_strength
old_scoring.theme_assist = scoring.theme_assist
old_scoring.classification = scoring.classification
old_scoring.datetime = Clock
old_strength.datetime = Clock

fixture = ROOT/'research'/'performance_round2_20261010'/'fixture'/'cache'
assert (fixture/'market.db').exists()

# Redirect config file paths, retain module history paths as read-only input.
for name, value in list(vars(config).items()):
    if isinstance(value, Path) and value.parent == original:
        setattr(config, name, fixture/value.name)
config.CACHE_DIR = fixture
config.ROOT = ROOT  # source fingerprints/templates remain actual sources
for name in ('CLOSE_DIR','MINUTE_DIR','LIVE_DIR','TREND_DIR'):
    old = getattr(close_monitor, name)
    setattr(close_monitor, name, fixture/old.name)
close_monitor.TREND_DIRS = {n: fixture/p.name for n, p in close_monitor.TREND_DIRS.items()}
intraday.REPORT_PATH = HERE/'validation_frozen.md'
series = {}
with df.db() as conn:
    for code in quotes:
        series[code] = df.load_kline(conn, 'kline','code',code)

real_consolidation, real_structure = trend_consolidation.attach, wyckoff_structure.attach
def no_persist(fn):
    def call(*args, **kwargs):
        kwargs['persist'] = False
        return fn(*args, **kwargs)
    return call

patches = [patch.object(df, 'realtime_quotes', return_value=quotes),
    patch.object(df, 'build_pool', return_value=pool_input),
    patch.object(df, 'fetch_ths_board_kline', side_effect=lambda c: deepcopy(inputs[c])),
    patch.object(df, 'fetch_klines_bulk', side_effect=lambda cs, **kw: ({c:deepcopy(series.get(c, [])) for c in cs if series.get(c)}, False)),
    patch.object(board_quote, 'fetch', return_value=board_quotes),
    patch.object(df, 'http_get', side_effect=RuntimeError('uncaptured external request')),
    patch.object(scoring, 'datetime', Clock), patch.object(board_trend, 'datetime', Clock),
    patch.object(strength, 'datetime', Clock), patch.object(intraday, 'datetime', Clock),
    patch.object(df, 'datetime', Clock), patch.object(close_monitor, 'datetime', Clock),
    patch.object(trend_consolidation, 'datetime', Clock), patch.object(wyckoff_structure, 'datetime', Clock),
    patch.object(session_context, 'datetime', Clock),
    patch.object(intraday.intraday_path, 'save_acquisition'),
    patch.object(intraday, 'save_observation'), patch.object(strength, 'save_observation'),
    patch.object(old_strength, 'save_observation'), patch.object(stock_strength, 'save_daily'),
    patch.object(scoring, 'append_history'), patch.object(old_scoring, 'append_history'),
    patch.object(trend_consolidation, 'attach', no_persist(real_consolidation)),
    patch.object(wyckoff_structure, 'attach', no_persist(real_structure))]
for p in patches: p.start()

results = {}
def one(label, module, old=False):
    config.SNAPSHOT_JSON.write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
    impl = board_trend._calculate
    if old: board_trend.calculate = old_board.calculate
    else: board_trend.calculate = new_calculate
    started = time.monotonic()
    result = module.run(mode='quick', progress=False)
    seconds = time.monotonic()-started
    results[label] = dict(seconds=seconds, phases=result.get('scan_performance'),
                          kline=result.get('kline_acquisition'), count=result['stock_count'])
    print(label, seconds, flush=True)
    return result

new_calculate = board_trend.calculate
try:
    if '--profile' in sys.argv:
        import cProfile
        profiler = cProfile.Profile()
        profiler.enable()
        one('profile', scoring)
        profiler.disable()
        profiler.dump_stats(str(HERE/'pipeline.prof'))
        raise SystemExit(0)
    old = one('old', old_scoring, True)
    cold = one('new_cold', scoring)
    warm = one('new_warm', scoring)
    # Compare the pre-audit calculation paths to the repaired paths. Both use the
    # corrected input-integrity/reference modules; external acquisition is mocked.
    allowed = {'elapsed','scan_performance','kline_acquisition','data_sources','em_status'}
    def clean(value):
        if isinstance(value, dict):
            return {k:clean(v) for k,v in value.items() if k not in allowed and k not in ('last_date','completed_date')}
        if isinstance(value, list): return [clean(v) for v in value]
        return value
    def differences(a, b, path=''):
        if type(a) != type(b): return [path+':type']
        if isinstance(a, dict):
            out = [path+':keys'] if set(a)!=set(b) else []
            for k in a.keys() & b.keys(): out.extend(differences(a[k], b[k], path+'/'+str(k)))
            return out
        if isinstance(a,list):
            out = [path+':length'] if len(a)!=len(b) else []
            for i,(x,y) in enumerate(zip(a,b)): out.extend(differences(x,y,path+'/'+str(i)))
            return out
        return [path] if a!=b else []
    raw_diff = differences(clean(old), clean(warm))
    # First-run reconstruction is an execution record, not a stock/board judgment.
    execution_diff = [p for p in raw_diff if p.startswith('/history_reference/generated')]
    diff = [p for p in raw_diff if p not in execution_diff]
    results['execution_differences'] = execution_diff
    results['differences'] = diff[:100]
    results['difference_count'] = len(diff)
    results['same_warm_cold'] = clean(cold) == clean(warm)
    results['stocks'] = len(warm['stocks'])+len(warm['coverage_catalog'])
    results['boards'] = len(warm['board_catalog'])
    (HERE/'frozen_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    assert not diff, diff[:30]
finally:
    for p in reversed(patches): p.stop()
