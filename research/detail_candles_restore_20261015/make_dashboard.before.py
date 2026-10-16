# -*- coding: utf-8 -*-
"""发布轻量看板及同版本地详情；完整离线看板由服务端按需导出。"""
import json
import sys
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
    for s in visible:
        try:
            ks = df.load_kline(conn, "kline", "code", s["code"], limit=60)
        except Exception:
            continue
        asof = s.get("signal_date") or completed_asof
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


@config.single_writer
def build(snap=None):
    if snap is None and not config.SNAPSHOT_JSON.exists():
        print("[ERR] 还没有数据快照，请先运行：python scoring.py full")
        return None
    if snap is None:
        snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    import price_only
    price_only.sanitize(snap)
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
    attach_klines(snap)
    import board_trend
    if not snap.get('board_opportunity_model'):
        board_trend.attach(snap, fetch=False)
    tpl = TPL.read_text(encoding="utf-8")
    import board_chart
    snap = board_chart.attach(snap)
    tpl = tpl.replace('/*__RADAR_SCRIPT__*/',(config.ROOT/'radar_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'stock_rank_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'ma_trend_ui.js').read_text(encoding='utf-8') + '\n' + (config.ROOT/'board_chart_ui.js').read_text(encoding='utf-8'))
    tpl=tpl.replace('/*__EMOTION_SCRIPT__*/',(config.ROOT/'emotion_ui.js').read_text(encoding='utf-8'))
    if PLACEHOLDER not in tpl:
        print("[ERR] 模板缺少数据占位符")
        return None
    lazy = '/*__UI_SCRIPT__*/' in tpl
    if lazy:
        import ui_payload
        snap['runtime_contract']['code_ui_payload_version'] = ui_payload.VERSION
        tpl = tpl.replace('/*__CSV_SCRIPT__*/', (config.ROOT / 'csv_export.js').read_text(encoding='utf-8'))
        tpl = tpl.replace('/*__UI_SCRIPT__*/', (config.ROOT / 'ui_client.js').read_text(encoding='utf-8'))
        package, generation = ui_payload.prepare(snap, tpl, OUT)
        payload = config.script_json(package)
    else:
        payload = config.script_json(snap)
    html = tpl.replace(PLACEHOLDER, payload)
    config.atomic_write_text(OUT, html)   # 原子写：避免浏览器读到半截页面
    if lazy:
        ui_payload.activate(generation, OUT)
    print(f"[OK] 看板已生成：{OUT}  ({len(html)/1024:.0f} KB)")
    return OUT


if __name__ == "__main__":
    sys.exit(0 if build() is not None else 1)
