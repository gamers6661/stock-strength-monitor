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


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


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
    list_fields = set(json.loads((config.ROOT / 'stock_list_fields.json').read_text(encoding='utf-8')))
    for group in ('stocks', 'coverage_catalog'):
        rows = []
        for s in full.get(group, []):
            row = {k: v for k, v in s.items() if k in list_fields and k not in ('k', 'kd', 'theme_relations', 'stock_strength_evidence')}
            if isinstance(row.get('intraday_path'), dict):
                row['intraday_path'] = {k: v for k, v in row['intraday_path'].items() if k != 'recent'}
            rows.append(row)
        result[group] = rows
    result['board_catalog'] = [dict(b, members=[{'code': r['code'], 'change_pct': r.get('change_pct')}
                                                 for r in b.get('members', [])])
                               for b in full.get('board_catalog', [])]
    result['ui_generation'] = token
    result['ui_lazy'] = True
    result.setdefault('runtime_contract', {})['code_ui_payload_version'] = VERSION
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
    source = (config.ROOT / 'csv_export.js').read_text(encoding='utf-8')
    fields = set(re.findall(r'\bs\.([A-Za-z_][A-Za-z0-9_]*)', source))
    result = {k: v for k, v in row.items() if k in fields}
    if 'theme_relations' in result:
        result['theme_relations'] = [{k: t.get(k) for k in ('name', 'state', 'peers')} for t in result['theme_relations']]
    if isinstance(result.get('intraday_path'), dict):
        result['intraday_path'] = {k: v for k, v in result['intraday_path'].items() if k != 'recent'}
    return result


def prepare(full, template, page):
    # Content hash also includes rendering/export implementation, not just market time.
    digest = hashlib.sha256()
    text = dumps(full)
    digest.update(text.encode('utf-8'))
    digest.update(template.encode('utf-8'))
    for name in ('ui_payload.py', 'ui_client.js', 'csv_export.js', 'csv_runner.js', 'stock_list_fields.json'):
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
                                    [('stock', s['code'], dumps(s)) for s in full.get(group, [])])
                    con.executemany('INSERT INTO detail VALUES(?,?,?)',
                                    [('csv', s['code'], dumps(csv_row(s))) for s in full.get(group, [])])
                con.executemany('INSERT INTO detail VALUES(?,?,?)',
                                [('board', b['id'], dumps(b)) for b in full.get('board_catalog', [])])
                for key, value in [('summary', dumps(packet).encode('utf-8')),
                                   ('full', text.encode('utf-8'))]:
                    con.execute('INSERT INTO meta VALUES(?,?)', (key, value))
                    con.execute('INSERT INTO meta VALUES(?,?)', (key + '.gz', gzip.compress(value, compresslevel=1)))
                con.execute('INSERT INTO meta VALUES(?,?)', ('template', template.encode('utf-8')))
                con.execute('INSERT INTO meta VALUES(?,?)', ('csv_formatter', (config.ROOT / 'csv_export.js').read_bytes()))
                con.execute('INSERT INTO meta VALUES(?,?)', ('csv_meta', dumps({k: full.get(k) for k in
                            ('quote_capture_at', 'generated_at', 'scan_completed_at', 'strength_model')}).encode('utf-8')))
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
    return json.loads(row[0])


def blob(token, key, page=None):
    with closing(connect(token, page)) as con:
        row = con.execute('SELECT value FROM meta WHERE id=?', (key,)).fetchone()
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


def export_csv(token, codes, contexts):
    if not isinstance(codes, list) or not 0 < len(codes) <= 10000 or len(set(codes)) != len(codes):
        raise ValueError('Invalid export selection')
    if not isinstance(contexts, dict):
        raise ValueError('Invalid display context')
    # Indexed rows only; do not parse the full market snapshot for each export.
    with closing(connect(token)) as con:
        rows = []
        for code in codes:
            if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
                raise ValueError('Invalid code')
            row = con.execute("SELECT value FROM detail WHERE kind='csv' AND id=?", (code,)).fetchone()
            if not row:
                raise ValueError('Unknown code')
            rows.append(json.loads(row[0]))
        meta = json.loads(con.execute("SELECT value FROM meta WHERE id='csv_meta'").fetchone()[0])
        formatter = con.execute("SELECT value FROM meta WHERE id='csv_formatter'").fetchone()
        if not formatter:
            raise LookupError('This formatter generation has expired')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is required for the shared CSV formatter')
    # Formatting is shared with the existing offline page, retaining all 228 columns.
    request = dumps({'rows': rows, 'data': {k: meta.get(k) for k in
                     ('quote_capture_at', 'generated_at', 'scan_completed_at', 'strength_model')},
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
