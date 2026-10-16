from pathlib import Path

root = Path(__file__).resolve().parents[2]

def edit(file, old, new):
    path = root/file
    text = path.read_text(encoding='utf-8')
    assert old in text, (file, old[:100])
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Keep the complete history for long-lived episodes; share it only within this scan.
p = root/'scoring.py'
s = p.read_text(encoding='utf-8')
start = s.index('    nk_path = config.CACHE_DIR / "no_kline.json"', s.index('def load_klines'))
end = s.index('    out = {}', start)
s = s[:start] + '''    import history_increment
    acquisition = history_increment.update(conn, codes, quotes, required_day,
                                           force=refresh, progress=progress)
    if telemetry is not None:
        telemetry.update(acquisition)
    history_cache = history_cache if history_cache is not None else {}
''' + s[end:]
s = s.replace('def load_klines(conn, codes, quotes, refresh=False, progress=True):',
'''def load_klines(conn, codes, quotes, refresh=False, progress=True,
                required_day=None, history_cache=None, telemetry=None):''')
s = s.replace('''        if c in no_kline and c not in have:
            out[c] = []
            continue
        ks = df.load_kline(conn, "kline", "code", c)''', '''        ks = df.load_kline(conn, "kline", "code", c)
        history_cache[c] = ks''')
s = s.replace('import radar\n', 'import radar\nimport scan_cache\n')
s = s.replace('    t_start = time.time()\n    scan_started_at', '    t_start = time.time()\n    timer = scan_cache.Timer(mode)\n    scan_started_at', 1)
s = s.replace('    quote_capture_at = datetime.now()', '    timer.mark("股票池与实时行情", "归属与外围")\n    quote_capture_at = datetime.now()', 1)
s = s.replace('    # 5. 板块\n', '    timer.mark("归属与外围", "板块历史")\n    # 5. 板块\n', 1)
s = s.replace('''    klines = load_klines(conn, codes, quotes, refresh=(mode in ("full", "close")), progress=progress)''', '''    timer.mark("板块历史", "正式日线增量")
    history_cache, kline_telemetry = {}, {}
    # Source-confirmed completed index dates provide a calendar bound; no weekday guessing.
    quote_dates = [q.get('quote_at', '')[:10] for q in quotes.values() if q.get('quote_at')]
    quote_day = Counter(quote_dates).most_common(1)[0][0] if quote_dates else ''
    historical_dates = [b.get('last_date') for b in boards if b.get('last_date') and b['last_date'] <= quote_day]
    required_day = quote_day if mode == 'close' else max(historical_dates, default=None)
    klines = load_klines(conn, codes, quotes, refresh=(mode == "full"), progress=progress,
                         required_day=required_day, history_cache=history_cache, telemetry=kline_telemetry)
    timer.mark("正式日线增量", "个股计算")
    snap['kline_acquisition'] = kline_telemetry''', 1)
s = s.replace('    _prev = _prev_stock_count()', '    _prev = int(previous_snapshot.get("stock_count") or 0)', 1)
s = s.replace('    formal=formal_histories(list(pool),conn)',
              "    formal={c: history_cache[c][-160:] if c in history_cache else df.load_kline(conn,'kline','code',c,limit=160) for c in pool}", 1)
start = s.index('    if config.SNAPSHOT_JSON.exists():\n        try:\n            previous_asof', s.index('def run('))
end = s.index('    if not stocks:', start)
s = s[:start] + '''    previous_asof = (previous_snapshot.get('strength_model') or {}).get('asof')
    if previous_asof and model['asof'] < previous_asof:
        raise DataNotReady(f"完成日线从 {previous_asof} 回退到 {model['asof']}，保留上一份快照")
''' + s[end:]
s = s.replace('    import board_trend\n    snap["board_trend_model"]', '    timer.mark("个股计算", "板块趋势与最新指数")\n    import board_trend\n    snap["board_trend_model"]', 1)
s = s.replace('    catalog, catalog_stats = coverage.build(', '    timer.mark("板块趋势与最新指数", "盘中与结构")\n    catalog, catalog_stats = coverage.build(', 1)
s = s.replace("lambda code: df.load_kline(conn,'kline','code',code)",
              "lambda code: history_cache[code] if code in history_cache else df.load_kline(conn,'kline','code',code)")
start = s.index('    config.atomic_write_text(\n        config.SNAPSHOT_JSON,', s.index('    session_context.attach(snap,quotes,formal,formal_calendar'))
end = s.index('    append_history(snap)', start)
s = s[:start] + '    timer.mark("盘中与结构", "观察留档与研究")\n' + s[end:]
s = s.replace('    # 研究报告随快照更新，页面与磁盘快照继续保持同一版本。', '''    scan_cache.flush()
    timer.mark("观察留档与研究", "快照写盘")
    snap['scan_performance'] = timer.result()
    snap['elapsed'] = round(time.time()-t_start, 3)
    # generated_at remains the judgment clock; performance clocks are separate.
    # 研究报告随快照更新，页面与磁盘快照继续保持同一版本。''', 1)
s = s.replace('    print(f"[RUN] 完成，耗时 {snap[\'elapsed\']}s ->',
'''    timer.mark("快照写盘", "页面发布")
    snap['scan_performance'] = timer.result()
    snap['elapsed'] = round(time.time()-t_start, 3)
    conn.close()
    print(f"[RUN] 扫描完成（含写盘），耗时 {snap['elapsed']}s ->''', 1)
p.write_text(s, encoding='utf-8')

# Pure metrics only. Industry ranks remain evaluated against the exact current sample.
edit('strength.py', 'import config\n', 'import config\nimport scan_cache\n')
edit('strength.py', '        m = day_metrics(bars, calendar)', '''        m = scan_cache.cached('day_metrics', code,
            [scan_cache.rules('strength.py', 'config.py'), bars, calendar],
            lambda: day_metrics(bars, calendar))''')
edit('strength.py', '    own_strength, strength_reference_count = stock_strength.score(metrics, contexts, ks)', '''    own_strength, strength_reference_count = stock_strength.score(metrics, contexts, ks)''')
# board historical replay can be expensive; cache by ALL bars/calendar/rules.
edit('board_trend.py', 'import datafeed\n', 'import datafeed\nimport scan_cache\n')
edit('board_trend.py', 'def calculate(bars, calendar, asof):', '''def calculate(bars, calendar, asof):
    return scan_cache.cached('board_replay', str(asof)+':'+str(bars[0] if bars else ''),
        [scan_cache.rules('board_trend.py', 'config.py'), bars, calendar, asof, RULES],
        lambda: _calculate(bars, calendar, asof))


def _calculate(bars, calendar, asof):''')

# Optional prepared snapshot avoids two additional full JSON reads per publication.
edit('make_dashboard.py', 'def build():', 'def build(snap=None):')
edit('make_dashboard.py', '    if not config.SNAPSHOT_JSON.exists():', '    if snap is None and not config.SNAPSHOT_JSON.exists():')
edit('make_dashboard.py', '    snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))',
     '    if snap is None:\n        snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))')
edit('serve.py', 'def publish_outputs():', 'def publish_outputs(snapshot=None):')
edit('serve.py', '''    snapshot = None
    try:
        page = make_dashboard.build()''', '''    publish_started = time.monotonic()
    try:
        if snapshot is None:
            snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
        page = make_dashboard.build(snapshot)''')
edit('serve.py', 'report.build())', 'report.build(snapshot))')
edit('serve.py', '            snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))\n', '')
edit('serve.py', '''    scoring.run(mode=mode, **kwargs)
    publish_outputs()''', '''    import scan_cache
    started = time.monotonic()
    try:
        snapshot = scoring.run(mode=mode, **kwargs)
        scan_seconds = time.monotonic()-started
        scan_cache.PROGRESS['stage'] = '页面发布'
        publish_outputs(snapshot)
        INIT['last_pipeline_performance'] = dict(version=scan_cache.VERSION,
            seconds=round(time.monotonic()-started, 3), scan_seconds=round(scan_seconds, 3),
            publish_seconds=round(time.monotonic()-started-scan_seconds, 3),
            phases=(snapshot.get('scan_performance') or {}).get('phases'),
            cache=(snapshot.get('scan_performance') or {}).get('cache'),
            kline_acquisition=snapshot.get('kline_acquisition'),
            published_at=datetime.now().isoformat(timespec='seconds'))
        config.atomic_write_text(config.CACHE_DIR/'last_pipeline_performance.json',
                                 json.dumps(INIT['last_pipeline_performance'], ensure_ascii=False))
        print('[PERF] 刷新至页面发布：' + json.dumps(INIT['last_pipeline_performance'], ensure_ascii=False))
    finally:
        scan_cache.flush()
        scan_cache.PROGRESS.update(active=False, stage=None)''')
edit('serve.py', "                 'member_refresh': weekly_members.status(),", "                 'member_refresh': weekly_members.status(),\n                 'scan_progress': __import__('scan_cache').progress(),\n                 'code_scan_cache_version': __import__('scan_cache').VERSION,")
edit('intraday.py', '    all_pairs = []\n    try:\n', '    import scan_cache\n    all_pairs = []\n    try:\n')
edit('intraday.py', '''            all_pairs = [json.loads(line) for line in PAIR_HISTORY_PATH.read_text(encoding="utf-8").splitlines()
                         if line.strip()]''', '''            all_pairs = scan_cache.read_json(PAIR_HISTORY_PATH, lines=True)''')
edit('intraday.py', 'json.loads(path.read_text(encoding="utf-8"))\n                         for path in sorted(CLOSE_HISTORY_DIR',
     'scan_cache.read_json(path)\n                         for path in sorted(CLOSE_HISTORY_DIR')

# SQL limiting does not truncate callers that require long complete episodes.
edit('datafeed.py', '    rows = conn.execute(q, (code,)).fetchall()\n    if table == "kline":', '''    if limit and int(limit) > 0:
        q = q.rsplit('ORDER BY date', 1)[0] + 'ORDER BY date DESC LIMIT ?'
        rows = list(reversed(conn.execute(q, (code, int(limit))).fetchall()))
    else:
        rows = conn.execute(q, (code,)).fetchall()
    if table == "kline":''')
edit('config.py', '    "workers": 10,       # 并发线程（腾讯K线不封IP）', '''    "workers": 10,       # 保持原并发，失败退避，不假定数据源不会限流。
    "increment_days": 20,
    "repair_per_scan": 50,''')
