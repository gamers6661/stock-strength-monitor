"""Only pure derived data is cached; keys include full input content and rule sources."""
from collections import OrderedDict, Counter
from copy import deepcopy
import hashlib
import json
import os
import sqlite3
import threading
import time
import sys
from functools import wraps

import config

VERSION = '后台增量缓存2-启动源码绑定'
_lock = threading.RLock()
_memory = OrderedDict()
_connections = {}
_rules = {}
COUNTS = Counter()
PROGRESS = {'active': False, 'stage': None}

# Capture before any scan, including modules imported lazily later in this
# process. A later disk edit must never label an old calculation as new code.
_SOURCE_HASHES = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in config.ROOT.glob('*.py')}


class SourceChanged(RuntimeError):
    """A restart is required before this process may calculate with edited rules."""


def signature(value):
    return hashlib.sha256(json.dumps([VERSION, list(sys.version_info[:2]), value], sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def rules(*files):
    """Bind cache keys to startup sources; reject edits until service restart."""
    parts = []
    for file in files:
        path = config.ROOT / file
        stamp = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        with _lock:
            if stamp not in _rules:
                _rules[stamp] = hashlib.sha256(path.read_bytes()).hexdigest()
            fingerprint = _rules[stamp]
            if fingerprint != _SOURCE_HASHES.get(str(path.resolve())):
                raise SourceChanged('源码已变化，请重启服务后重新计算：' + file)
            parts.append(fingerprint)
    return parts


def _connection():
    path = config.CACHE_DIR / 'scan_features.db'
    key = str(path)
    if key not in _connections:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=1, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS feature(ns TEXT,id TEXT,key TEXT,payload TEXT,PRIMARY KEY(ns,id))')
        _connections[key] = conn
    return _connections[key]


def get(ns, identity, key):
    if os.environ.get('STOCK_DISABLE_FEATURE_CACHE') == '1':
        return None
    scope = (str(config.CACHE_DIR), ns, str(identity), key)
    with _lock:
        if scope in _memory:
            COUNTS['memory_hits'] += 1
            _memory.move_to_end(scope)
            return deepcopy(_memory[scope])
        try:
            row = _connection().execute('SELECT payload FROM feature WHERE ns=? AND id=? AND key=?',
                                       (ns, str(identity), key)).fetchone()
            if row:
                value = json.loads(row[0])
                _remember(scope, value)
                COUNTS['disk_hits'] += 1
                return value  # _remember owns a copy; the decoded value belongs to this caller.
        except (sqlite3.Error, OSError, ValueError):
            COUNTS['errors'] += 1
        COUNTS['misses'] += 1
    return None


def _remember(scope, value):
    _memory[scope] = deepcopy(value)
    _memory.move_to_end(scope)
    while len(_memory) > 5000:
        _memory.popitem(last=False)


def put(ns, identity, key, value):
    if os.environ.get('STOCK_DISABLE_FEATURE_CACHE') == '1':
        return
    with _lock:
        _remember((str(config.CACHE_DIR), ns, str(identity), key), value)
        try:
            _connection().execute('INSERT OR REPLACE INTO feature VALUES(?,?,?,?)',
                (ns, str(identity), key, json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)))
        except (sqlite3.Error, OSError, ValueError):
            COUNTS['errors'] += 1


def cached(ns, identity, inputs, compute):
    try:
        key = signature(inputs)
    except (TypeError, ValueError):
        # Caching must never make otherwise usable source data unavailable.
        COUNTS['errors'] += 1
        return deepcopy(compute())
    value = get(ns, identity, key)
    if value is not None:
        return value  # get already isolated the caller from the cache.
    value = compute()
    if value is not None:
        put(ns, identity, key, value)
    return deepcopy(value)


def flush():
    with _lock:
        for conn in _connections.values():
            try:
                if conn.execute('SELECT COUNT(*) FROM feature').fetchone()[0] > 12000:
                    conn.execute('DELETE FROM feature WHERE rowid NOT IN (SELECT rowid FROM feature ORDER BY rowid DESC LIMIT 10000)')
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                COUNTS['errors'] += 1


class Timer:
    def __init__(self, mode):
        self.started = self.last = time.monotonic()
        self.phases = {}
        self.counts = dict(COUNTS)
        PROGRESS.update(active=True, stage='准备', mode=mode, started=time.time())

    def mark(self, label, next_stage=None):
        now = time.monotonic()
        self.phases[label] = round(now - self.last, 3)
        self.last = now
        PROGRESS['stage'] = next_stage or label

    def result(self):
        return dict(version=VERSION, seconds=round(time.monotonic()-self.started, 3),
                    phases=dict(self.phases), cache={k: v-self.counts.get(k, 0) for k, v in COUNTS.items()})


def progress():
    return dict(PROGRESS, running_seconds=round(time.time()-PROGRESS['started'], 1)
                if PROGRESS.get('active') else None)


def run_guard(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            flush()
            PROGRESS.update(active=False, stage=None)
    return call


_json_files = {}


def read_json(path, lines=False):
    """Append-only JSONL reads only its new tail; replaced files invalidate by inode/time."""
    try:
        stat = path.stat()
        key = (str(path), lines)
        prior = _json_files.get(key)
        stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if prior and prior[0] == stamp:
            return deepcopy(prior[1])
        if lines:
            append = prior and prior[0][0] == stat.st_ino and stat.st_size > prior[0][1]
            with path.open('rb') as stream:
                # Confirm old tail too; a replacement of the same/larger size is not an append.
                if append:
                    start, tail = prior[2]
                    stream.seek(start)
                    append = stream.read(len(tail)) == tail
                # Resume at the last COMPLETE line, not at a saved partial tail's file size.
                offset = prior[3] if append else 0
                stream.seek(offset)
                added = []
                for line in stream.read(stat.st_size-offset).splitlines(keepends=True):
                    if not line.endswith(b'\n'):
                        break
                    offset += len(line)
                    if not line.strip():
                        continue
                    try:
                        added.append(json.loads(line.decode('utf-8')))
                    except (ValueError, UnicodeError):
                        COUNTS['errors'] += 1
                stream.seek(max(0, stat.st_size-128))
                anchor = (stream.tell(), stream.read())
            value = prior[1] + added if append else added
        else:
            value = json.loads(path.read_text(encoding='utf-8'))
            anchor = None
            offset = stat.st_size
        _json_files[key] = (stamp, value, anchor, offset)
        return deepcopy(value)
    except (OSError, ValueError):
        return [] if lines else {}
