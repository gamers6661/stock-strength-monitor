"""检查正在运行的服务、磁盘快照与实际通过 HTTP 送出的看板模型一致。"""
import json
from urllib.request import urlopen, Request

import config
import strength
import stock_strength
import attack_model
import intraday
import close_monitor
import trend_consolidation
import wyckoff_structure
import session_context
import board_trend
import board_center
import board_opportunity
import radar_opportunity
import board_quote
import weekly_members
import scoring
import price_only
from datetime import datetime


def get(url):
    with urlopen(url, timeout=15) as response:
        return response.read()


def run(base="http://127.0.0.1:8848"):
    status = json.loads(get(base + "/__status"))
    snapshot = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    import market_strength
    assert status['code_market_strength_version']==status['snapshot_market_strength_version']==market_strength.VERSION
    assert status['code_market_strength_hash']==status['snapshot_market_strength_hash']==market_strength.IMPLEMENTATION_HASH
    market_strength.validate(snapshot)
    if snapshot.get('emotion_relay'):
        import emotion_relay
        assert status['code_emotion_relay_hash']==status['snapshot_emotion_relay_hash']==emotion_relay.IMPLEMENTATION_HASH
        emotion_relay.validate(snapshot)
    if snapshot.get('ma_trend'):
        import ma_trend
        assert status['code_ma_trend_hash']==status['snapshot_ma_trend_hash']==ma_trend.IMPLEMENTATION_HASH
        ma_trend.validate(snapshot)
        if snapshot.get('session')=='已收盘' and snapshot.get('close_daily_verified_at'):
            assert snapshot['market_strength']['coverage']['trend_valid']>0, '收盘日线已就绪但趋势有效覆盖为零'
            total=len(snapshot['stocks'])+len(snapshot.get('coverage_catalog',[]))
            assert len(snapshot['ma_trend']['pending'])<total, '收盘日线已就绪但所有均线状态待核验'
            assert snapshot['ma_trend'].get('minute_needed',0)==0, '正式收盘结果仍依赖分钟过程核验'
    html = get(base + "/dashboard.html").decode("utf-8")
    text_report = (config.ROOT / "snapshot_report.md").read_text(encoding="utf-8")
    marker = "var DATA = "
    assert marker in html, "服务送出的页面没有模型数据"
    served, _ = json.JSONDecoder().raw_decode(html.split(marker, 1)[1].lstrip())
    import ui_payload
    served = ui_payload.unpack(served)
    if served.get('ui_lazy'):
        assert status.get('code_ui_payload_version') == ui_payload.VERSION
        assert served['ui_generation'] == status.get('ui_generation')
        brief = served
        served = ui_payload.full(brief['ui_generation'])
        assert brief == ui_payload.summary(served, brief['ui_generation']), '轻量页面与同版完整数据不一致'
        first = served['stocks'][0]
        from urllib.parse import urlencode
        response = json.loads(get(base + '/__ui/detail?' + urlencode(
            {'version': brief['ui_generation'], 'kind': 'stock', 'id': first['code']})))
        assert response['version'] == brief['ui_generation'] and response['item'] == first
    assert status["phase"] == "ready" and status["last_scan_ok"], "服务未就绪或上次扫描失败"
    assert status["code_model_version"] == strength.VERSION
    assert status["code_strength_version"] == stock_strength.VERSION
    assert status.get('code_close_refresh_version') == scoring.CLOSE_REFRESH_VERSION, '服务尚未载入新版收盘更新流程，需要重启'
    assert status.get('code_fund_reference_version') == price_only.VERSION, '服务尚未停用资金参考，需要重启'
    assert snapshot.get('fund_reference_version') == served.get('fund_reference_version') == price_only.VERSION
    assert snapshot.get('fund_available') is False and snapshot.get('fund_confirmation', {}).get('enabled') is False
    assert not any(s.get('fund_today_yi') is not None or s.get('fund_positive_all') is not None for s in served['stocks']+served.get('coverage_catalog', []))
    assert snapshot.get('close_refresh_version') == served.get('close_refresh_version') == scoring.CLOSE_REFRESH_VERSION, '收盘更新流程与实际页面快照不一致'
    if served.get('close_daily_verified_at'):
        day = served['close_daily_verified_at'][:10]
        assert served['strength_model']['asof'] == served['close_strong_board']['asof'] == day
        assert status.get('snapshot_close_daily_verified_at') == served['close_daily_verified_at']
        assert not served['close_strong_board'].get('today_pending')
    assert status["code_board_trend_version"] == board_trend.VERSION
    assert status['code_board_catalog_version'] == board_center.VERSION
    assert status['snapshot_board_catalog_version'] == snapshot['board_catalog_version'] == served['board_catalog_version'] == board_center.VERSION
    assert status['snapshot_board_opportunity_version'] == market_strength.VERSION
    assert snapshot['board_opportunity_model'] == served['board_opportunity_model']
    assert status['snapshot_board_opportunity_counts'] == served['board_opportunity_model']['counts']
    board_opportunity.validate(served)
    for board in served['board_catalog']:
        assert board['opportunity'] == next(b['opportunity'] for b in snapshot['board_catalog'] if b['id'] == board['id'])
    if served.get('ui_generation'):
        import gzip
        from urllib.parse import urlencode
        request = Request(base+'/__ui/summary?'+urlencode({'version':served['ui_generation']}), headers={'Accept-Encoding':'gzip'})
        with urlopen(request, timeout=15) as response:
            assert response.headers.get('Content-Encoding') == 'gzip'
            compressed = ui_payload.unpack(json.loads(gzip.decompress(response.read())))
        assert compressed['board_opportunity_model'] == served['board_opportunity_model']
        assert compressed['radar_opportunity'].get('last_close_review')==served['radar_opportunity'].get('last_close_review')
        assert compressed['market_strength']==served['market_strength']
        assert compressed['board_catalog']==ui_payload.summary(served,served['ui_generation'])['board_catalog']
        example = served['board_catalog'][0]
        response = json.loads(get(base+'/__ui/detail?'+urlencode({'version':served['ui_generation'],'kind':'board','id':example['id']})))
        assert response['item']['opportunity'] == example['opportunity']
    assert '当前强势' in html and 'market-strength-table' in html
    assert served['market_strength']==snapshot['market_strength']
    if snapshot.get('emotion_relay'):
        assert served['emotion_relay']==snapshot['emotion_relay']
        emotion_relay.validate(served)
        assert 'function renderEmotion' in html and '板块／题材' in html
    if snapshot.get('ma_trend'):
        assert served['ma_trend']==snapshot['ma_trend']
        ma_trend.validate(served)
    market_strength.validate(served)
    if served['session'] in ('集合竞价', '竞价结束'):
        import copy
        expected_auction = copy.deepcopy(served)
        board_center.attach_auction(expected_auction)
        for actual, expected in zip(served['board_catalog'], expected_auction['board_catalog']):
            assert actual.get('member_auction') == expected['member_auction'], '板块竞价汇总与有效个股报价不一致'
            assert actual.get('members') == expected.get('members'), '板块竞价明细与有效个股报价不一致'
        assert 'function boardAuctionMetrics(b)' in html and '竞价涨幅排序' in html
    assert status['member_refresh']['interval_days'] == snapshot['member_refresh']['interval_days'] == served['member_refresh']['interval_days'] == config.MEMBER_REFRESH_DAYS == 7
    industry_names = {b['name'] for b in served['board_catalog'] if b['type'] == 'industry'}
    theme_names = {b['name'] for b in served['board_catalog'] if b['type'] == 'theme'}
    catalog = board_center._catalog()
    assert catalog['industry'] <= industry_names, '同花顺行业目录入口缺失'
    assert catalog['theme'] <= theme_names, '同花顺概念目录入口缺失'
    assert status["code_intraday_model_version"] == intraday.VERSION
    assert status["code_intraday_rule_version"] == config.INTRADAY_RULE_VERSION
    assert status["last_publish_ok"] is True
    assert status["snapshot_generated_at"] == snapshot["generated_at"]
    assert snapshot["factor_model_version"] == served["factor_model_version"] == strength.VERSION
    assert snapshot["strength_model"]["strength_version"] == served["strength_model"]["strength_version"] == stock_strength.VERSION
    assert snapshot["intraday_model"]["version"] == served["intraday_model"]["version"] == intraday.VERSION
    assert snapshot["intraday_model"]["rule_version"] == served["intraday_model"]["rule_version"] == config.INTRADAY_RULE_VERSION
    assert status["snapshot_intraday_rule_version"] == config.INTRADAY_RULE_VERSION
    assert snapshot["generated_at"] == served["generated_at"]
    assert strength.VERSION in text_report and snapshot["generated_at"] in text_report, "文字日报仍是旧快照"
    assert len(snapshot["stocks"]) == len(served["stocks"]) > 0
    assert served['strength_model']['core_required_bars'] == 25
    for b in served['board_catalog']:
        assert (b['trend_rank'] is not None) == b['ranking_eligible']
        idx = b.get('index_trend')
        if idx and idx.get('ready'):
            assert idx['asof'] == served['strength_model']['asof']
            assert len(served['board_trend_model']['calendar']) >= 22
            assert idx['advance_signal'] == (idx['ma5'] > idx['ma10']
                and idx['ma5'] > idx['ma5_prev'] and idx['ma10'] > idx['ma10_prev']
                and idx['close'] >= idx['ma5'] and idx['close'] >= idx['ma10'])
            if idx['strong_advance']:
                assert idx['advance_signal'] and idx['priority_observation'] and not idx['weak']
            if idx['weak']:
                assert not idx['observing'] and not idx['priority_observation']
            if idx['ma20_support_established']:
                assert idx['observing'] and idx['close'] >= idx['ma20']
            if idx['support_observation']:
                assert idx['ma20_support_established'] and not idx['priority_observation']
            if idx['pullback_atr'] is not None:
                assert idx['pullback_atr'] > 0
                assert idx['episode_start'] <= idx['pullback_atr_asof'] < idx['pullback_start'] <= idx['asof']
        current = b.get('index_current')
        if idx:
            assert current is not None, '板块缺少最新指数判断入口'
        if current and current.get('ready') and current.get('mode') == 'current':
            quote = b['index_quote']
            captured = datetime.fromisoformat(served['board_trend_model']['captured_at'])
            phase=served['board_trend_model']['phase']
            # A preserved morning generation is explicitly labelled as a
            # reference. Its index facts must be valid at that original clock,
            # rather than being reclassified as a new 11:30 closing quote.
            reference=(b.get('market_strength') or {}).get('mode','')
            prefix='午休参考 · 原时点 '
            if phase=='午间休市' and reference.startswith(prefix):
                captured=datetime.fromisoformat(reference[len(prefix):])
                assert captured.date()==datetime.fromisoformat(served['quote_capture_at']).date()
                assert '09:30:00'<=str(captured)[11:19]<='11:32:59'
                phase='早盘'
            assert board_quote.freshness(quote, captured, phase) is None
            assert current['quote_at'] == quote['quote_at'] and current['code'] == idx['code'] == quote['code']
            assert current['name'] == b['name'] == quote['name']
            bars = [k for k in board_trend.load(idx['code']) if k['date'] < quote['date']]
            assert abs(bars[-1]['close']-quote['previous_close']) <= .01
            if current['confirmation'] != '收盘确认':
                for period in (5,10,20):
                    assert abs(current['ma'+str(period)]-(sum(k['close'] for k in bars[-period+1:])+quote['price'])/period) < 1e-7
                assert current['advance_signal'] == (current['ma5'] > current['ma10']
                    and current['ma5'] > current['ma5_prev'] and current['ma10'] > current['ma10_prev']
                    and current['close'] >= current['ma5'] and current['close'] >= current['ma10'])
                assert current['repair_confirmed'] is False
            if current['strong_advance']:
                assert current['priority_observation'] and not current['weak']
        elif current and not current.get('ready'):
            assert not current.get('priority_observation') and not current.get('strong_advance')
    assert served['board_trend_model']['current_ready'] == sum(bool((b.get('index_current') or {}).get('ready')) for b in served['board_catalog'])
    assert snapshot['board_trend_model']['version'] == served['board_trend_model']['version'] == board_trend.VERSION
    assert status['snapshot_board_trend_version'] == board_trend.VERSION
    assert all(set(row["stock_strength_parts"]) == set(stock_strength.WEIGHTS)
               for row in served["stocks"]), "页面个股缺少三个周期进攻分"
    assert served["attack_monitor"]["version"] == attack_model.LIVE_VERSION
    consolidation=served.get('trend_consolidation') or {}
    structure=served.get('wyckoff_structure') or {}
    assert status['code_structure_version'] == status['snapshot_structure_version'] == wyckoff_structure.VERSION
    assert structure.get('version') == wyckoff_structure.VERSION
    assert structure == snapshot['wyckoff_structure']
    assert structure['count'] == len(structure['rows'])
    source_rows={r['code']:r for r in served['stocks']+served.get('coverage_catalog',[])}
    context=served['session_context']
    assert status['code_session_context_version']==status['snapshot_session_context_version']==session_context.VERSION
    assert context==snapshot['session_context'] and context['version']==session_context.VERSION
    assert context['price_judged_count']==sum(r['session_context']['quote_valid'] for r in source_rows.values())
    for row in source_rows.values():
        c=row['session_context']
        assert c['version']==session_context.VERSION
        assert c.get('setup_state'), '整理条件未单独说明'
        evidence=c.get('history_evidence') or {}
        if evidence.get('valid'):
            assert evidence['count']>=evidence['required']==40
        if c['quote_valid'] and c['price_basis_valid']:
            assert c.get('current_label'), '有效报价没有最新观察说明'
            if c.get('partial_history'):
                assert not c['monitor_candidate'], '短历史样本不能产生完整结构候选'
                assert c.get('available_ma') and c.get('reason'), '短历史样本缺少可用周期和原因'
            else:
                assert c.get('structure_state'), '完整历史有效报价没有最新结构解释'
        if c['stage'] in ('午间休市','已收盘'):
            assert not c['monitor_candidate'], '休市参考不应产生新候选'
        if c['monitor_candidate']:
            assert c['quote_valid'] and c['price_basis_valid'] and c['atr20']>0 and not c['risks']
        for key in ('strength_delta1','strength_delta5'):
            if row.get(key) is not None:assert row[key+'_source'] in ('真实收盘留档','历史日线重算')
    assert 'function sessionContextDetail(s)' in html and '昨日收盘衔接当日判断' in text_report
    for item in structure['rows']:
        assert source_rows[item['code']]['wyckoff_structure'] == item
        assert item['created_asof'] <= item['evidence_asof'] <= structure['asof']
        assert item['atr0'] > 0 and item['platform_high'] >= item['platform_low']
        assert all(e['day'] > item['created_asof'] and e['observed_at'] for e in item['events'])
        if item['current_structure_clear']:
            assert item['live_valid'] and not item['restrictions']
        for attempt in item['attempts']:
            if (attempt.get('retest') or {}).get('confirmed_at'):
                assert attempt['volume_at'] < attempt['retest']['touch_at'] < attempt['retest']['confirmed_at']
    assert 'function structureDetail(code)' in html and '固定平台量价结构观察' in text_report
    assert consolidation.get('version') == trend_consolidation.VERSION
    assert consolidation == snapshot['trend_consolidation']
    assert len(consolidation.get('rows',[])) == consolidation.get('count',0)
    assert not ({r['code'] for r in consolidation.get('rows',[])} &
                {r['code'] for r in consolidation.get('completed_rows',[])})
    assert all(r.get('phase')=='completed' and r.get('eligible') is False
               for r in consolidation.get('completed_rows',[]))
    for item in consolidation.get('rows',[]):
        assert item['trend_online'] is True
        if not item.get('downgraded_observation') and not item.get('reference_only'): assert item['live_trend_online'] is True
        if item.get('downgraded_observation'):
            assert item.get('observation_history_qualified') and not item.get('current_breakout_confirmed')
        assert item['attack_trend_online'] is True and item['days'] >= 2
        assert item['impulse5_pct'] >= 15 or item['impulse10_pct'] >= 20
        assert item['impulse_end'] < item['consolidation_start']
        assert item['baseline_asof'] < consolidation['day']
        assert item['phase'] in ('consolidating','initial')
        assert item.get('post_breakout_days',0) == 0
        if item['needs_repair_confirmation'] and item['phase']=='initial': assert item['repair_samples'] >= 2
    for item in consolidation.get('completed_rows',[]):
        assert item['attack_trend_online'] is True and item['days'] >= 2
        assert item['completion_confirmed'] is True and not item.get('trend_exited')
        assert item['completion_type'] in ('平台突破转强','回踩修复转强')
        assert item['completion_evidence'] and item['completed_at']
        assert item.get('tracking_state') in ('holding','ma5_pullback','breakout_failed','structure_cooling',
                                              'risk_cooling','ma10_test','ma10_repaired','ma10_downgraded',
                                              'ma10_close_downgraded','ma10_repair_pending','ma20_test','ma20_repaired','ma20_pending')
        if item.get('current_breakout_confirmed'):
            assert item['completion_position_holds'] and item['current_ma5_holds']
            assert item['live_trend_online'] is True
        if item.get('tracking_state')=='ma10_test': assert item['ma10_below_samples']<2
        assert item.get('completion_samples',2) >= 2
    for item in consolidation.get('withdrawn_rows',[]):
        assert item['trend_exited'] and not item['current_breakout_confirmed']
        assert item['exit_line']=='MA20'
        assert item['tracking_state'] in ('ma20_lost','ma20_repair_pending','ma20_close_lost')
    for item in consolidation.get('pending_rows',[]):
        if item.get('completion_confirmed'): assert item['reference_only'] and not item['current_breakout_confirmed']
    if consolidation.get('review_mode') == 'rule_upgrade_close_review':
        assert consolidation['current_count'] == 0
        assert all(r.get('reference_only') is True for r in consolidation['rows'])
    if served.get('session') in ('早盘','午盘','尾盘','午间休市'):
        by_code_consolidation={r['code']:r for r in served['stocks']+served.get('coverage_catalog',[])}
        for item in consolidation.get('rows',[]):
            if item.get('reference_only'): continue
            row=by_code_consolidation[item['code']]
            assert row['intraday_observation_available'] and row['intraday_price_basis_comparable'] is True
            if not item.get('downgraded_observation'):
                assert row['price'] >= row['intraday_ma10_trigger_price']
                assert row['intraday_trend_ok'] is True
            if item['stage'] in ('初步转强','初步突破'):
                assert item['confirmation_samples'] >= 2
    assert 'id="work-consolidation-list"' in html and 'id="work-followup-section"' in html
    assert 'id="work-trend-comparison"' not in html
    if served.get("session") in ("早盘", "午盘", "尾盘"):
        all_rows = served["stocks"] + served.get("coverage_catalog", [])
        watched = [r for r in all_rows if r.get("attack_watch_candidate")]
        assert {r["code"] for r in watched} == {r["code"] for r in served["attack_monitor"]["rows"]}
        for row in watched:
            assert row["intraday_quote_fresh"] and row["intraday_price_basis_comparable"] is True
            assert row["live_attack_tier"] == "A" and not row["intraday_serious_weakness"]
            assert row["live_attack_price_tier"] == "A"
            assert row['live_attack_fund']['weight'] == 0 and row['live_attack_fund']['score'] is None
            expected_score = row["live_attack_price_score"]
            assert row["live_attack_score"] == expected_score
            assert row["intraday_trend_ok"] is True
        assert served["attack_monitor"]["count"] == len(watched)
        by_code_attack = {r["code"]: r for r in watched}
        assert all(r["trend_tier"] == by_code_attack[r["code"]].get("daily_attack_tier")
                   for r in served["attack_monitor"]["rows"])
    assert 'id="work-attack-list"' in html
    assert html.count('id="work-attack-list"') == 1 and 'id="work-new-list"' not in html
    assert all("intraday_quote_status" in row and "intraday_trend_state" in row
               and "current_pullback_candidate" in row for row in served["stocks"])
    assert served["intraday_model"]["price_basis_version"] == intraday.PRICE_BASIS_VERSION
    assert not any(row.get("current_strong_candidate") or row.get("current_pullback_candidate")
                   for row in served["stocks"] if row.get("intraday_quote_fresh") is not True)
    for row in served["stocks"] + served.get("coverage_catalog", []):
        if row.get("intraday_quote_fresh") is not True:
            continue
        prior_online = row.get("intraday_prior_daily_trend_online") == 1
        qualification = row.get("current_strong_qualification") or {}
        assert qualification.get("上一完成日日线趋势成立") == prior_online, row["code"]
        assert not (prior_online and row.get("startup_candidate")), row["code"]
        flags = ("current_strong_candidate", "startup_candidate", "intraday_active_candidate", "intraday_repair_candidate")
        assert sum(bool(row.get(k)) for k in flags) <= 1, row["code"]
        if row.get("intraday_price_basis_comparable") is not True:
            assert row.get("intraday_trend_ok") is not True, row["code"]
            ma_dependent_flags = ("current_strong_candidate", "startup_candidate",
                                  "current_pullback_candidate", "entry_watch")
            assert not any(row.get(k) for k in ma_dependent_flags), row["code"]
            assert row.get("intraday_transition") is None, row["code"]
            assert row.get("intraday_risk_level") != "低", row["code"]
            assert not any(flag in (row.get("intraday_risk_flags") or [])
                           for flag in ("现价失守盘中MA10", "现价失守盘中MA20")), row["code"]
        else:
            assert row.get("intraday_atr20_status") in ("可用", "待核验"), row["code"]
            if row.get("intraday_atr20_status") == "可用":
                assert row.get("intraday_atr20") is not None, row["code"]
            else:
                assert row.get("intraday_atr20") is None, row["code"]
                assert row.get("live_dist_atr") is None, row["code"]
                assert row.get("intraday_risk_level") != "低", row["code"]
                assert not row.get("current_pullback_candidate"), row["code"]
                assert (row.get("current_pullback_qualification") or {}).get("位置未过热") is not True, row["code"]
            for period in close_monitor.LINES:
                holds = row.get(f"intraday_ma{period}_current_holds")
                note = row.get(f"intraday_ma{period}_current_note") or ""
                if holds is True:
                    assert "现价守住" in note, (row["code"], period, note)
                elif holds is False:
                    assert "现价低于" in note, (row["code"], period, note)
                time_note = row.get(f"intraday_ma{period}_minute_note") or ""
                if time_note and holds is True:
                    assert "现价已在线上" in time_note or "现价守住" in time_note, (row["code"], period, time_note)
                if time_note and holds is False:
                    assert "现价已在线下" in time_note or "现价低于" in time_note, (row["code"], period, time_note)
        if row.get("startup_candidate"):
            assert all(row["startup_qualification"].values()), row["code"]
            assert row["intraday_observation_state"] == "初步转强，待收盘确认", row["code"]
        event = row.get("intraday_transition")
        if event == "扫描观察到收复MA10":
            assert row["price"] >= row["intraday_ma10_trigger_price"], row["code"]
        elif event == "扫描观察到失守MA10":
            assert row["price"] < row["intraday_ma10_trigger_price"], row["code"]
    board = snapshot["close_strong_board"]
    assert board == served["close_strong_board"]
    for period in close_monitor.LINES:
        key = f"trend_ma{period}_observation"
        assert snapshot[key] == served[key]
        observation = served[key]
        assert observation["price_basis_version"] == intraday.PRICE_BASIS_VERSION
        assert observation["pending_count"] == len(observation["pending_rows"])
        if snapshot.get("session") in ("早盘", "午盘", "尾盘"):
            by_code = {r["code"]: r for r in served["stocks"] + served.get("coverage_catalog", [])}
            for item in observation["main_rows"] + observation["reclaim_rows"]:
                row = by_code[item["code"]]
                assert row.get("intraday_price_basis_comparable") is True, item["code"]
                # Independently computed floats can straddle a four-decimal
                # rounding tie. Both displays must still match the raw MA.
                exact_ma = row[f"intraday_ma{period}_exact"]
                display_tolerance = .00005 + 1e-12
                assert abs(item["provisional_ma"] - exact_ma) <= display_tolerance, item["code"]
                assert abs(row[f"intraday_ma{period}"] - exact_ma) <= display_tolerance, item["code"]
                assert item["threshold_price"] == row[f"intraday_ma{period}_trigger_price"], item["code"]
                assert item["distance_pct"] == round(row[f"intraday_distance_ma{period}_pct"], 3), item["code"]
                assert item["distance_atr"] == row[f"intraday_distance_ma{period}_atr"], item["code"]
                if item in observation["reclaim_rows"]:
                    assert item["status"] == "15分钟内收回", item["code"]
                    assert row[f"intraday_ma{period}_current_holds"] is True, item["code"]
    assert snapshot["intraday_new_strength"] == served["intraday_new_strength"]
    if snapshot.get("session") in ("早盘", "午盘", "尾盘"):
        by_code = {r["code"]: r for r in served["stocks"] + served.get("coverage_catalog", [])}
        home = served["intraday_new_strength"]["rows"]
        assert {r["code"] for r in home} == {c for c, r in by_code.items()
            if r.get("intraday_quote_fresh") and (r.get("current_strong_candidate") or r.get("startup_candidate"))}
        assert all(r["kind"] == by_code[r["code"]]["intraday_observation_state"] for r in home)
    assert board["version"] == close_monitor.VERSION
    # 盘中尚无正式收盘板时 asof 为空；只有已形成的收盘板才对应归档文件。
    if board.get("asof"):
        archive_path = close_monitor.CLOSE_DIR / (board["asof"] + ".json")
        if archive_path.exists():
            archived = json.loads(archive_path.read_text(encoding="utf-8"))
            assert archived["stocks"] == board["stocks"], "收盘主榜与正式留档不一致"
        # 盘中展示的是正式收盘留档，不能用次日变化的样本池重新构建来比较。
        if (board["asof"] == snapshot["strength_model"]["asof"]
                and board.get("observed_at") == snapshot["generated_at"]):
            assert [s["code"] for s in board["stocks"]] == [s["code"] for s in
                close_monitor.build_close_board(snapshot)["stocks"]]
    if snapshot.get("session") == "已收盘" and not board.get("today_pending"):
        assert board.get("asof"), "收盘阶段的正式主榜缺少日期"
        archived = json.loads((close_monitor.CLOSE_DIR / (board["asof"] + ".json")).read_text(encoding="utf-8"))
        assert archived["stocks"] == board["stocks"]
        assert "## 收盘强势主榜 · " + board["asof"] in text_report
    assert 'id="work-close-table"' in html and 'id="work-consolidation-pending"' in html
    assert 'id="work-trend-list"' not in html
    assert 'function uiTrendPullbackItems(s)' in html and 'id="stock-trend-pullbacks"' in html
    assert 'MA5/10/20当前与分钟时间关系' in html and 'ATR20完整窗口' in html
    print(f"OK pid={status['pid']} scan={status['last_scan']} snapshot={snapshot['generated_at']} "
          f"daily={strength.VERSION} strength={stock_strength.VERSION} intraday={intraday.VERSION} "
          f"valid_quotes={status['snapshot_intraday_valid_quotes']} rows={len(served['stocks'])}")


if __name__ == "__main__":
    run()
