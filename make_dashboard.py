# -*- coding: utf-8 -*-
"""发布轻量看板及同版本地详情；完整离线看板由服务端按需导出。"""
import json
import hashlib
import sqlite3
import sys
import time
from contextlib import closing

import config

TPL = config.ROOT / "dashboard_template.html"
OUT = config.ROOT / "dashboard.html"
PLACEHOLDER = "/*__DATA__*/null"


def attach_klines(snap, top_n=None):
    """给可点击的个股附加精简收盘走势，确保详情有图可看。"""
    if top_n is None:
        top_n = len(snap.get("stocks") or [])
    try:
        import datafeed as df
        conn = df.db()
    except Exception as e:
        print(f"[WARN] 无法读取K线，看板将不含走势图：{e}")
        return snap
    with closing(conn):
        return _attach_klines(snap, top_n, conn)


def _attach_klines(snap, top_n, conn):
    import datafeed as df
    n_ok = 0
    scored = (snap.get("stocks") or [])[:top_n]
    visible = scored + (snap.get("coverage_catalog") or [])
    chart_codes = {s["code"] for s in scored}
    chart_codes.update(s["code"] for s in snap.get("coverage_catalog") or []
                       if s.get("trend_online"))
    completed_asof = (snap.get("strength_model") or {}).get("asof")
    day = str(snap.get('quote_capture_at') or snap.get('generated_at') or '')[:10]
    fetch_states = {}
    try:
        for code,payload in conn.execute('SELECT code,payload FROM kline_fetch_state'):
            try:fetch_states[code] = json.loads(payload).get('data_fetch') or {}
            except (ValueError,AttributeError):continue
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc):raise
    try:counts=list(conn.execute('SELECT date,COUNT(*) FROM kline GROUP BY date ORDER BY date'))
    except sqlite3.OperationalError:counts=[]
    threshold=max((v for d,v in counts),default=0)*.5
    calendar=[d for d,v in counts if v>=threshold and d<=day]
    for s in visible:
        s.pop('chart_data_state', None)
        try:
            ks = df.load_kline(conn, "kline", "code", s["code"], limit=60)
        except Exception:
            continue
        asof = s.get("signal_date") or completed_asof
        attach_completed_candles(s, ks, completed_asof or asof, day=day)
        state = chart_acquisition_state(s, ks, fetch_states.get(s['code']) or {}, day, completed_asof or asof)
        if state:s['chart_data_state'] = state
        import observed_history
        availability=(snap.get('data_availability') or {}).get(s['code']) or s.get('data_availability')
        if availability:s['data_availability']=availability
        if availability and availability.get('kind')=='inferred_suspension':
            s['chart_data_state']=dict(availability,label='停牌（按缺失规则推定）')
            suspension=(s.get('emotion_relay') or {}).get('suspension') or {}
            if suspension and not suspension.get('inferred'):
                s['chart_data_state']=dict(kind='verified_suspension',label='停牌（公告已核验）',
                    checked_at=availability.get('checked_at'),basis=suspension.get('reason') or '已取得日期有效的停牌记录')
        actual=s.get('chart_history') or s.get('strength_history') or []
        if actual:
            observation=observed_history.annotation(actual,calendar,day)
            if observed_history.quote_traded(s,day):
                observation['suspension_days']=[d for d in observation['suspension_days'] if d!=day]
            suspension=(s.get('emotion_relay') or {}).get('suspension') or {}
            if suspension and not suspension.get('inferred'):
                observation['verified_suspension_days']=[d for d in observation['suspension_days']
                    if str(suspension.get('start') or '')[:10]<=d and (not suspension.get('end') or d<str(suspension['end'])[:10])]
            s['chart_observation']=observation
        if asof:
            ks = [k for k in ks if k["date"] <= asof]
            # quick 快照收盘后使用腾讯收盘报价补齐当日完成K，数据库历史K可能仍到昨日。
            if ks and s.get("signal_date") and ks[-1]["date"] < s["signal_date"] and s.get("signal_close"):
                ks.append({"date": s["signal_date"], "close": s["signal_close"]})
        if ks and float(ks[-1]["close"]) > 0:
            s["last_completed_date"] = str(ks[-1]["date"])
            s["last_completed_close"] = round(float(ks[-1]["close"]), 2)
            if len(ks) >= 2 and float(ks[-2]["close"]) > 0:
                s["last_completed_change_pct"] = round(
                    (float(ks[-1]["close"]) / float(ks[-2]["close"]) - 1) * 100, 2)
        elif s.get("last_close") and float(s["last_close"]) > 0:
            # 报价中的昨收可作价格参考；缺少完成日线时不臆造涨跌幅或收盘日期。
            s["last_completed_close"] = round(float(s["last_close"]), 2)
        if len(ks) >= 5 and s["code"] in chart_codes:
            s["k"] = [round(float(k["close"]), 2) for k in ks]
            s["kd"] = [str(k["date"])[5:] for k in ks]
            n_ok += 1
    print(f"[OK] 已附加 {n_ok} 只个股的走势序列")
    return snap


def attach_completed_candles(row, bars, asof, day=None):
    """Supply display-only OHLC even when live scoring has no valid context."""
    import intraday
    import observed_history
    relay = row.get('emotion_relay') or {}
    day = day or str(relay.get('quote_at') or '')[:10] or asof
    paused = relay.get('suspended_current') or (not relay.get('valid') and any(
        b.get('halted') and b.get('date') == day for b in relay.get('history', [])))
    if not asof:
        return False
    completed = [b for b in observed_history.traded_bars(bars) if b.get('date') and b['date'] <= asof and intraday._valid_historical_price_bar(b)]
    if not completed:
        return False
    existing=row.get('chart_history') or row.get('strength_history') or []
    if existing and existing[-1].get('date','')>=completed[-1]['date']:
        return False
    bases = {(b.get('price_basis'), b.get('price_basis_source')) for b in completed}
    trusted = {('qfq', source) for source in intraday._QFQ_HISTORY_SOURCES}
    trusted.update(('raw', source) for source in intraday._RAW_HISTORY_SOURCES)
    if len(bases) != 1 or not bases.issubset(trusted):
        return False
    row['chart_history'] = [dict(b) for b in completed[-60:]]
    row['chart_source'] = 'completed_daily_history'
    row['chart_at'] = completed[-1]['date']
    return True


def chart_acquisition_state(row, bars, state, day, asof):
    """A same-batch healthy control supports suspicion, never legal suspension."""
    import intraday
    if not state or str(state.get('checked_at') or '')[:10] != day or state.get('kind') == 'ok':
        return None
    relay = row.get('emotion_relay') or {}
    if relay.get('suspended_current') or any(b.get('halted') and b.get('date') == day for b in relay.get('history', [])):
        return None  # Existing verified suspension label takes precedence.
    completed = [b for b in bars if b.get('date') and asof and b['date'] <= asof]
    if (len(completed) >= 5 and completed[-1]['date'] == asof
            and all(intraday._valid_historical_price_bar(b) for b in completed)):
        return None
    at = intraday.parse_quote_timestamp(row.get('intraday_quote_at'))
    traded = (at and at.date().isoformat() == day and row.get('price_basis') == 'raw'
        and row.get('price_basis_source') in intraday._RAW_QUOTE_SOURCES
        and any(isinstance(row.get(k),(int,float)) and row[k] > 0 for k in ('volume_shou','amount_wan')))
    isolated = (state.get('kind') == 'isolated_empty' and state.get('empty_responses') == 2
                and state.get('peer_success_count', 0) > 0 and not relay.get('valid') and not traded)
    return dict(kind='suspected_suspension' if isolated else 'data_pending',
        label='疑似停牌' if isolated else '日K线数据待更新',checked_at=state.get('checked_at'),
        basis=('同批同源有'+str(state.get('peer_success_count',0))+'只股票返回有效K线，本股两次有效空响应；尚未确认停牌。'
               if isolated else '采集未完成或本股有有效成交证据，不能根据空值、报错或超时认定停牌。'),
        evidence=state)


def publication_source_hash():
    names = ['config.py', 'make_dashboard.py', 'ui_payload.py', 'dashboard_template.html', 'stock_list_fields.json', 'board_journal.py', 'board_journal_ui.css']
    names += sorted(p.name for p in config.ROOT.glob('*.js'))
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update((config.ROOT / name).read_bytes())
    return digest.hexdigest()


@config.single_writer
def build(snap=None):
    profile = {}
    profile_start = [time.monotonic()]

    def mark(label):
        now = time.monotonic()
        profile[label] = round(now - profile_start[0], 3)
        profile_start[0] = now

    if snap is None and not config.SNAPSHOT_JSON.exists():
        print("[ERR] 还没有数据快照，请先运行：python scoring.py full")
        return None
    if snap is None:
        snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    source_snap = snap
    import price_only
    price_only.sanitize(snap)
    mark("准备快照")
    import scoring
    import attack_model
    import board_opportunity
    import radar_opportunity
    import market_strength
    import ma_trend
    import emotion_relay
    snap['runtime_contract'] = dict(code_close_refresh_version=scoring.CLOSE_REFRESH_VERSION,
                                   code_fund_reference_version=price_only.VERSION,
                                   code_attack_model_version=attack_model.LIVE_VERSION,
                                   code_board_opportunity_version=board_opportunity.VERSION)
    snap['runtime_contract']['code_radar_opportunity_version']=radar_opportunity.VERSION
    snap['runtime_contract']['code_market_strength_version']=market_strength.VERSION
    snap['runtime_contract']['code_market_strength_hash']=market_strength.IMPLEMENTATION_HASH
    snap['runtime_contract']['code_ma_trend_version']=ma_trend.VERSION
    snap['runtime_contract']['code_ma_trend_hash']=ma_trend.IMPLEMENTATION_HASH
    snap['runtime_contract']['code_emotion_relay_version']=emotion_relay.VERSION
    snap['runtime_contract']['code_emotion_relay_hash']=emotion_relay.IMPLEMENTATION_HASH
    attach_klines(snap, config.RUNTIME['kline_inline_top'])
    mark("K线附加")
    import board_trend
    if not snap.get('board_opportunity_model'):
        board_trend.attach(snap, fetch=False)
    mark("板块趋势")
    tpl = TPL.read_text(encoding="utf-8")
    import board_chart
    snap = board_chart.attach(snap, refresh=True)
    mark("板块图")
    # Board-page observations are a separate projection; shared strength results stay intact.
    import board_dynamics
    snap['board_dynamics'] = board_dynamics.build(snap)
    mark("板块动态")
    import board_journal
    snap["board_journal"] = board_journal.build(snap)
    mark("题材日报")
    # V3独立采样与全站发布共享同一后端结果，完整离线版固定发布时证据。
    import stock_selection
    snap['stock_selection'] = stock_selection.page_model(snap)
    snap['runtime_contract']['code_refresh_policy_version'] = 'shared-round-5m-v1'
    snap['refresh_policy'] = dict(mode='shared', interval_seconds=config.RUNTIME['refresh_seconds'],
                                  source_round_at=snap.get('quote_capture_at'), path_sampling_seconds=120)
    snap['runtime_contract']['code_stock_selection_version']=stock_selection.VERSION
    snap['runtime_contract']['code_stock_selection_hash']=stock_selection.IMPLEMENTATION_HASH
    mark('个股强度V3')
    tpl = tpl.replace('</head>', '<style id="board-journal-style">'+(config.ROOT/'board_journal_ui.css').read_text(encoding='utf-8')+'</style></head>')
    tpl = tpl.replace('</head>', '<style>'+ (config.ROOT/'stock_selection_ui.css').read_text(encoding='utf-8')+'</style></head>')
    tpl = tpl.replace('/*__RADAR_SCRIPT__*/',(config.ROOT/'radar_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'stock_rank_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'stock_selection_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'ma_trend_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'board_chart_ui.js').read_text(encoding='utf-8'))
    tpl=tpl.replace('/*__EMOTION_SCRIPT__*/',(config.ROOT/'emotion_ui.js').read_text(encoding='utf-8'))
    tpl=tpl.replace('/*__BOARD_DYNAMICS_SCRIPT__*/',(config.ROOT/'board_dynamics_ui.js').read_text(encoding='utf-8')+'\n'+(config.ROOT/'auction_ui.js').read_text(encoding='utf-8')+'\n'+(config.ROOT/'board_journal_ui.js').read_text(encoding='utf-8')+'\n'+"var ssFallbackStock=showStock;showStock=function(code,boardId){return typeof ssModel==='function'&&ssModel()&&ssModel().items[code]?ssShow(code):ssFallbackStock(code,boardId);};")
    mark("模板与脚本")
    if PLACEHOLDER not in tpl:
        print("[ERR] 模板缺少数据占位符")
        return None
    lazy = '/*__UI_SCRIPT__*/' in tpl
    if lazy:
        import ui_payload
        snap['runtime_contract']['code_ui_payload_version'] = ui_payload.VERSION
        tpl = tpl.replace('/*__CSV_SCRIPT__*/', (config.ROOT / 'csv_export.js').read_text(encoding='utf-8'))
        tpl = tpl.replace('/*__UI_SCRIPT__*/', (config.ROOT / 'ui_client.js').read_text(encoding='utf-8'))
        snap['publication_sources'] = publication_source_hash()
        package, generation = ui_payload.prepare(snap, tpl, OUT)
        mark("UI生成")
        payload = config.script_json(package)
    else:
        payload = config.script_json(snap)
    html = tpl.replace(PLACEHOLDER, payload)
    config.atomic_write_text(OUT, html)   # 原子写：避免浏览器读到半截页面
    if lazy:
        ui_payload.activate(generation, OUT)
    mark("写盘与激活")
    publish_profile = dict(profile, total=round(sum(profile.values()), 3))
    snap['publish_performance'] = publish_profile
    source_snap['publish_performance'] = publish_profile
    print(f"[OK] 看板已生成：{OUT}  ({len(html)/1024:.0f} KB)")
    return OUT


if __name__ == "__main__":
    sys.exit(0 if build() is not None else 1)
