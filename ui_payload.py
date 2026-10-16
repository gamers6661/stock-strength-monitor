"""Immutable local UI generations. Lists, details and exports share one token."""
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

import config

VERSION = 'local-ui-2'
IMPLEMENTATION_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def encode_detail(value):
    return gzip.compress(dumps(value).encode('utf-8'), compresslevel=1)


def decode_detail(value):
    # Prior immutable generations used TEXT; continue serving them unchanged.
    if isinstance(value, bytes) and value.startswith(b'\x1f\x8b'):
        value = gzip.decompress(value)
    return json.loads(value)


def json_key(key):
    # JavaScript object properties and the persisted JSON detail payload use text keys.
    if isinstance(key,str):
        return key
    if key is None or isinstance(key,(int,float)):
        return dumps(key)
    raise TypeError('Unsupported JSON object key')


def pack(value):
    keys, strings, shapes, ki, si, shape_index = [], [], [], {}, {}, {}

    def base36(n):
        chars = '0123456789abcdefghijklmnopqrstuvwxyz'
        result = ''
        while n:
            n, r = divmod(n, 36)
            result = chars[r] + result
        return result or '0'

    def visit(x):
        if isinstance(x, dict):
            shape = []
            for k, v in x.items():
                k=json_key(k)
                if k not in ki:
                    ki[k] = len(keys)
                    keys.append(k)
                shape.append(ki[k])
            identity = tuple(shape)
            if identity not in shape_index:
                shape_index[identity] = len(shapes)
                shapes.append(shape)
            return ['^' + base36(shape_index[identity])] + [visit(v) for v in x.values()]
        if isinstance(x, list):
            return [visit(v) for v in x]
        if isinstance(x, str) and (len(x) >= 4 or x.startswith(('~', '^'))):
            if x not in si:
                si[x] = len(strings)
                strings.append(x)
            return '~' + base36(si[x])
        return x
    root = visit(value)
    return {'format': VERSION, 'keys': keys, 'strings': strings, 'shapes': shapes, 'root': root}


def unpack(packet):
    if packet.get('format') not in ('local-ui-1', VERSION):
        return packet

    def visit(x):
        if isinstance(x, dict):
            return {json_key(packet['keys'][int(k)]): visit(v) for k, v in x.items()}
        if isinstance(x, list):
            if x and isinstance(x[0], str) and x[0].startswith('^'):
                shape = packet['shapes'][int(x[0][1:], 36)]
                return {json_key(packet['keys'][key]): visit(v) for key, v in zip(shape, x[1:])}
            return [visit(v) for v in x]
        if isinstance(x, str) and x.startswith('~'):
            return packet['strings'][int(x[1:], 36)]
        if isinstance(x, str) and x.startswith('\x01') and 'shapes' not in packet:
            return packet['strings'][int(x[1:])]
        return x
    return visit(packet['root'])


def summary(full, token):
    result = dict(full)
    result.pop('direction_observations', None)
    result.pop('emotion_observations', None)
    result.pop('market_strength_close_input', None)
    result.pop('market_strength_morning_input', None)
    list_fields = set(json.loads((config.ROOT / 'stock_list_fields.json').read_text(encoding='utf-8')))
    list_fields.add('market_strength')
    list_fields.add('ma_trend')
    list_fields.add('emotion_relay')
    list_fields.update(('industry','industry_detail','themes','concepts'))
    for group in ('stocks', 'coverage_catalog'):
        rows = []
        for s in full.get(group, []):
            row = {k: v for k, v in s.items() if k in list_fields and k not in ('k', 'kd', 'theme_relations', 'stock_strength_evidence')}
            if isinstance(row.get('intraday_path'), dict):
                row['intraday_path'] = {k: v for k, v in row['intraday_path'].items() if k != 'recent'}
            if row.get('market_strength'):
                import market_strength
                row['market_strength']=market_strength.brief(row['market_strength'])
                row.pop('radar_opportunity', None)  # Legacy duplicate; canonical detail retains it.
            if row.get('ma_trend'):
                import ma_trend
                row['ma_trend']=ma_trend.brief(row['ma_trend'])
            if row.get('emotion_relay'):
                import emotion_relay
                row['emotion_relay']=emotion_relay.brief(row['emotion_relay'])
            rows.append(row)
        result[group] = rows
    result['board_catalog'] = [dict(b, members=[{'code': r['code'], 'change_pct': r.get('change_pct')}
                                                 for r in b.get('members', [])])
                               for b in full.get('board_catalog', [])]
    for b in result['board_catalog']:
        b.pop('index_chart', None)  # Frozen OHLC is loaded with the full board detail.
    if full.get('market_strength'):
        import market_strength
        for b in result['board_catalog']:
            full_m=b['market_strength'];b['market_strength']=market_strength.brief(full_m)
            b['market_strength']['emotion_parts']={'R0':full_m['emotion_parts'].get('R0')}
            b['opportunity']=dict(b['opportunity'],market_strength=b['market_strength'])
    if full.get('radar_opportunity'):
        model=dict(full['radar_opportunity'])
        if full.get('market_strength'):
            model.pop('by_code', None)
        else:
            model['by_code']={c:radar_brief(r) for c,r in model['by_code'].items()}
        result['radar_opportunity']=model
        if 'by_code' in model:
            for group in ('stocks','coverage_catalog'):
                for r in result[group]:
                    if r['code'] in model['by_code']:r['radar_opportunity']=model['by_code'][r['code']]
    result['ui_generation'] = token
    result['ui_lazy'] = True
    result.setdefault('runtime_contract', {})['code_ui_payload_version'] = VERSION
    return result


def radar_brief(row):
    keys=('code','name','version','day','judged_at','source_at','R0','E0','M0','price','daily_tier','daily_asof',
          'live_attack_score','risk','status','current','main_label','labels','trade_restriction','board_relation_status','display_label','opportunity_kinds','sort_rank')
    result={k:row.get(k) for k in keys}
    if row.get('market_strength'):
        import market_strength
        result['market_strength']=market_strength.brief(row['market_strength'])
    result['boards']=[{k:b.get(k) for k in ('name','type','selected','peers_qualified')} for b in row.get('boards',[])]
    result['first_observed_at']=row.get('first_observed_at') or min((v['event']['first_observed_at'] for v in row.get('categories',{}).values() if v.get('event')),default=None)
    return result


def store_root(page=None):
    return (Path(page).parent if page else config.ROOT) / 'cache' / 'ui_payloads'


def db_path(token, page=None):
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{24}', token):
        raise ValueError('Invalid generation')
    path = store_root(page) / (token + '.db')
    if not path.is_file():
        raise LookupError('This generation has expired. Update the page first.')
    return path


def connect(token, page=None):
    return sqlite3.connect(db_path(token, page).as_uri() + '?mode=ro', uri=True)


def csv_row(row):
    if row.get('market_strength'):
        return {k:row.get(k) for k in ('code','name','change_pct','market_strength','ma_trend','emotion_relay') if k in row}
    source = (config.ROOT / 'csv_export.js').read_text(encoding='utf-8')
    fields = set(re.findall(r'\bs\.([A-Za-z_][A-Za-z0-9_]*)', source))
    result = {k: v for k, v in row.items() if k in fields}
    if 'theme_relations' in result:
        result['theme_relations'] = [{k: t.get(k) for k in ('name', 'state', 'peers')} for t in result['theme_relations']]
    if isinstance(result.get('intraday_path'), dict):
        result['intraday_path'] = {k: v for k, v in result['intraday_path'].items() if k != 'recent'}
    return result


def chart_projection(full):
    """Freeze display-only latest candles; never feed them back into scoring."""
    import math
    import intraday

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def valid(bar):
        return (all(number(bar.get(k)) and bar[k] > 0 for k in ('open', 'high', 'low', 'close'))
                and bar['low'] <= min(bar['open'], bar['close'])
                and bar['high'] >= max(bar['open'], bar['close']) and bar['high'] >= bar['low'])

    captured = intraday.parse_quote_timestamp(full.get('quote_capture_at') or full.get('generated_at'))
    verified = intraday.parse_quote_timestamp(full.get('close_daily_verified_at'))
    if not captured:
        return full
    day = captured.date().isoformat()
    archived_quotes = None

    def display_quote(row, at):
        """Recover omitted display fields from this generation's exact raw batch."""
        nonlocal archived_quotes
        if row.get('last_close_semantics') and row.get('price_basis_source'):
            return row
        if archived_quotes is None:
            archived_quotes = {}
            path = intraday.HISTORY_DIR / 'acquisitions' / (day + '.jsonl.gz')
            if path.is_file():
                try:
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        for line in stream:
                            record = json.loads(line)
                            if record.get('captured_at') == full.get('quote_capture_at'):
                                archived_quotes = {values[0]: dict(zip(record['fields'], values))
                                                   for values in record['rows']}
                                break
                except (OSError, EOFError, ValueError, KeyError):
                    archived_quotes = {}
        quote = archived_quotes.get(row.get('code')) or {}
        if (intraday.parse_quote_timestamp(quote.get('quote_at')) != at
                or any(quote.get(k) != row.get(k) for k in ('price','open','high','low','last_close'))):
            return row
        return dict(row, **quote)
    # A later database update must not turn an intraday generation into a closing chart.
    formal = (full.get('session') == '已收盘' and captured.hour >= 15 and verified is not None
              and verified.date() == captured.date() and verified.hour >= 15 and verified <= captured)
    daily = {}
    if formal and config.KLINE_DB.is_file():
        try:
            with closing(sqlite3.connect(config.KLINE_DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
                fields = ('code', 'date', 'open', 'close', 'high', 'low', 'volume', 'price_basis', 'price_basis_source')
                for values in con.execute('SELECT ' + ','.join(fields) + ' FROM kline WHERE date=?', (day,)):
                    bar = dict(zip(fields, values))
                    daily[bar.pop('code')] = bar
        except sqlite3.Error:
            pass  # Real quoted OHLC remains available when formal history is unavailable.
    result = dict(full)
    for group in ('stocks', 'coverage_catalog'):
        projected = []
        for row in full.get(group, []):
            model = row.get('market_strength') or {}
            context = model.get('price_context') or {}
            at = intraday.parse_quote_timestamp(model.get('quote_at'))
            bars = row.get('strength_history') or []
            prior = [b for b in bars if b.get('date') and b['date'] < day]
            quote = row
            # Display scaling does not require a full MA20 window. A valid
            # current quote plus trusted observed bars can draw a short chart.
            if not context.get('valid') and at and prior:
                quote = display_quote(row, at)
                display=intraday.align_price_basis(dict(quote,quote_at=str(at)),prior,
                    [b['date'] for b in prior],observation_day=day,quote_at=str(at),allow_partial=True)
                if display.get('valid'):
                    factor=display['scale_factor'];context=display
                    prior=[dict(b,**{k:b[k]*factor for k in ('open','high','low','close')}) for b in prior if valid(b)]
                    bars=prior
            if (not context.get('valid') or not at or at.date() != captured.date()
                    or at > captured or context.get('quote_day') != day or not bars
                    or not prior or context.get('last_history_date') != prior[-1].get('date')):
                projected.append(row)
                continue
            factor = context.get('scale_factor')
            bar = daily.get(row['code'])
            source = 'quoted_ohlc'
            if (bar and number(factor) and factor > 0 and valid(bar)
                    and bar.get('price_basis') == context.get('history_basis')
                    and bar.get('price_basis_source') == context.get('history_basis_source')):
                bar = dict(bar, **{k: bar[k] * factor for k in ('open', 'high', 'low', 'close')})
                source = 'formal_daily'
            else:
                volume = quote.get('volume_shou')
                bar = dict(date=day, open=row.get('open'), high=row.get('high'), low=row.get('low'),
                           close=row.get('price'), volume=volume * 100 if number(volume) and volume >= 0 else None)
            if not valid(bar):
                projected.append(row)
                continue
            # Replace by date, rather than appending, even if a future producer includes today already.
            by_date = {b['date']: dict(b) for b in prior if valid(b)}
            by_date[day] = dict(bar, aligned_price_basis='quote_scale')
            item = dict(row, chart_history=[by_date[d] for d in sorted(by_date)][-61:],
                        chart_source=source, chart_at=at.isoformat(sep=' ', timespec='seconds'))
            if row.get('chart_observation'):
                item['chart_observation']=dict(row['chart_observation'],suspension_days=[
                    d for d in row['chart_observation'].get('suspension_days',[]) if d!=day])
            projected.append(item)
        if group in full:
            result[group] = projected
    return result


def prepare(full, template, page):
    full = chart_projection(full)
    # Content hash also includes rendering/export implementation, not just market time.
    digest = hashlib.sha256()
    text = dumps(full)
    digest.update(text.encode('utf-8'))
    digest.update(template.encode('utf-8'))
    digest.update(IMPLEMENTATION_HASH.encode('ascii'))
    for name in ('ui_client.js', 'csv_export.js', 'csv_runner.js', 'stock_list_fields.json'):
        digest.update((config.ROOT / name).read_bytes())
    token = digest.hexdigest()[:24]
    brief = summary(full, token)
    packet = pack(brief)
    directory = store_root(page)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (token + '.db')
    if not path.exists():
        fd, tmp = tempfile.mkstemp(prefix='ui-', suffix='.tmp', dir=str(directory))
        import os
        os.close(fd)
        try:
            with closing(sqlite3.connect(tmp)) as con:
                con.execute('CREATE TABLE detail(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))')
                con.execute('CREATE TABLE meta(id TEXT PRIMARY KEY,value BLOB)')
                for group in ('stocks', 'coverage_catalog'):
                    con.executemany('INSERT INTO detail VALUES(?,?,?)',
                                    [('stock', s['code'], encode_detail(s)) for s in full.get(group, [])])
                    con.executemany('INSERT INTO detail VALUES(?,?,?)',
                                    [('csv', s['code'], encode_detail(csv_row(s))) for s in full.get(group, [])])
                con.executemany('INSERT INTO detail VALUES(?,?,?)',
                                [('board', b['id'], encode_detail(b)) for b in full.get('board_catalog', [])])
                # Full data is read on demand for offline export/verification. Do not
                # write a second uncompressed 250MB copy on every market refresh.
                con.execute('INSERT INTO meta VALUES(?,?)', ('full.gz', gzip.compress(text.encode('utf-8'), compresslevel=1)))
                for key, value in [('summary', dumps(packet).encode('utf-8'))]:
                    con.execute('INSERT INTO meta VALUES(?,?)', (key, value))
                    con.execute('INSERT INTO meta VALUES(?,?)', (key + '.gz', gzip.compress(value, compresslevel=1)))
                con.execute('INSERT INTO meta VALUES(?,?)', ('template', template.encode('utf-8')))
                con.execute('INSERT INTO meta VALUES(?,?)', ('csv_formatter', (config.ROOT / 'csv_export.js').read_bytes()))
                csv_meta={k:full.get(k) for k in ('quote_capture_at','generated_at','scan_completed_at','strength_model','market_strength','ma_trend','stock_board_ranking','emotion_relay') if k in full}
                csv_meta['board_stock_rankings']={b['id']:dict(name=b['name'],ranking=b.get('stock_ranking')) for b in full.get('board_catalog',[]) if b.get('stock_ranking')}
                csv_meta['ui_generation']=token
                con.execute('INSERT INTO meta VALUES(?,?)', ('csv_meta', dumps(csv_meta).encode('utf-8')))
                html = template.replace('/*__DATA__*/null', config.script_json(packet)).encode('utf-8')
                con.execute('INSERT INTO meta VALUES(?,?)', ('page.gz', gzip.compress(html, compresslevel=1)))
                con.commit()
            Path(tmp).replace(path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    return packet, token


def detail(token, kind, identity, page=None):
    if kind not in ('stock', 'board') or not isinstance(identity, str) or len(identity) > 160:
        raise ValueError('Invalid detail request')
    with closing(connect(token, page)) as con:
        row = con.execute('SELECT value FROM detail WHERE kind=? AND id=?', (kind, identity)).fetchone()
    if not row:
        raise KeyError('Unknown item')
    return decode_detail(row[0])


def blob(token, key, page=None):
    with closing(connect(token, page)) as con:
        row = con.execute('SELECT value FROM meta WHERE id=?', (key,)).fetchone()
        if not row and key == 'full':
            compressed = con.execute('SELECT value FROM meta WHERE id=?', ('full.gz',)).fetchone()
            if compressed:
                return gzip.decompress(compressed[0])
    if not row:
        raise KeyError('Unknown payload')
    return row[0]


def active_generation():
    try:
        return (store_root() / 'active.txt').read_text(encoding='ascii').strip()
    except OSError:
        return None


def activate(token, page):
    directory = store_root(page)
    config.atomic_write_text(directory / 'active.txt', token)
    # Only managed immutable generations, retain current plus latest prior backup.
    others = sorted((p for p in directory.glob('*.db') if p.name != token + '.db'),
                    key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in others[1:]:
        if re.fullmatch(r'[a-f0-9]{24}\.db', path.name):
            try:
                path.unlink()
            except PermissionError:
                pass  # A reader may still be exporting this generation on Windows.


def full(token, page=None):
    return json.loads(blob(token, 'full', page))


def export_board_csv(token, identities, page=None):
    if not isinstance(identities, list) or len(identities) > 10000 or any(not isinstance(x, str) or len(x) > 160 for x in identities) or len(set(identities)) != len(identities):
        raise ValueError('Invalid board selection')
    import csv
    import io
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    with closing(connect(token, page)) as con:
        boards=[]
        for identity in identities:
            row = con.execute("SELECT value FROM detail WHERE kind='board' AND id=?", (identity,)).fetchone()
            if not row:
                raise ValueError('Unknown board')
            boards.append(decode_detail(row[0]))
        if boards and boards[0].get('emotion_relay'):
            writer.writerow(['ID','名称','类型','确认主板成员','成员趋势参考分','当前在板数','已核验当前梯队','上涨占比%','反馈中位%','有效同行','应覆盖同行','有效覆盖%','源行情','接力规则','实现哈希','UI版本','完整接力依据'])
            for board in boards:
                m=board.get('emotion_relay') or {}
                writer.writerow([board['id'],board['name'],board['type'],len(board.get('member_codes') or []),
                    (board.get('market_strength') or {}).get('trend_score'),m.get('limit_count'),dumps(m.get('ladder')),
                    m.get('up_pct'),m.get('median_return_pct'),m.get('valid'),m.get('expected'),m.get('coverage_pct'),
                    m.get('source_at'),m.get('version'),m.get('implementation_hash'),token,dumps(m)])
            return ('\ufeff'+output.getvalue()).encode('utf-8')
        writer.writerow(['ID','名称','趋势分','情绪分','主导周期','阶段','版本','UI版本','完整模型依据'])
        for board in boards:
            model=board['market_strength'];identity=board['id']
            writer.writerow([identity, board['name'], model['trend_score'], model['emotion_score'],
                             model['dominant_period'], model['phase'], model['version'], token, dumps(model)])
    return ('\ufeff'+output.getvalue()).encode('utf-8')


def export_csv(token, codes, contexts):
    if not isinstance(codes, list) or not 0 <= len(codes) <= 10000 or len(set(codes)) != len(codes):
        raise ValueError('Invalid export selection')
    if not isinstance(contexts, dict):
        raise ValueError('Invalid display context')
    # Indexed rows only; do not parse the full market snapshot for each export.
    with closing(connect(token)) as con:
        meta = json.loads(con.execute("SELECT value FROM meta WHERE id='csv_meta'").fetchone()[0])
        rows = []
        for code in codes:
            if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
                raise ValueError('Invalid code')
            row = con.execute("SELECT value FROM detail WHERE kind='csv' AND id=?", (code,)).fetchone()
            if not row:
                ranking=(meta.get('board_stock_rankings',{}).get(contexts.get('rankBoardId'),{}).get('ranking') or {})
                item=(ranking.get('items') or {}).get(code)
                if contexts.get('view')!='ranking' or not item:raise ValueError('Unknown code')
                rows.append(dict(code=code,name=item.get('name') or code,market_strength={}))
            else:rows.append(decode_detail(row[0]))
        formatter = con.execute("SELECT value FROM meta WHERE id='csv_formatter'").fetchone()
        if not formatter:
            raise LookupError('This formatter generation has expired')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is required for the shared CSV formatter')
    # Formatting is shared with the existing offline page, retaining all 228 columns.
    request = dumps({'rows': rows, 'data': {k: meta.get(k) for k in
                     ('quote_capture_at', 'generated_at', 'scan_completed_at', 'strength_model','market_strength','ma_trend','stock_board_ranking','board_stock_rankings','emotion_relay','ui_generation') if k in meta},
                     'contexts': contexts, 'formatter': formatter[0].decode('utf-8')})
    result = subprocess.run([node, str(config.ROOT / 'csv_runner.js')], input=request.encode('utf-8'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('CSV formatting failed')
    return result.stdout


def offline_html(token):
    template = blob(token, 'template').decode('utf-8')
    data = full(token)
    data['ui_generation'] = token
    return template.replace('/*__DATA__*/null', config.script_json(data)).encode('utf-8')
