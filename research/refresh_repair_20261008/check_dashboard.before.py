"""验证生成看板的数据契约；发现错误时以非零状态退出。"""
import json
from pathlib import Path
import config
import radar
import strength
import stock_strength
import wyckoff_structure
import intraday

html = Path('dashboard.html').read_text(encoding='utf-8')
start = html.index('var DATA = ') + len('var DATA = ')
snap, _ = json.JSONDecoder().raw_decode(html[start:].lstrip())
rows = snap['stocks']
saved = json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert saved['generated_at'] == snap['generated_at'], '页面与快照时间不一致'
assert saved['factor_model_version'] == snap['factor_model_version'], '页面与快照版本不一致'
assert rows, '有效样本为空'
assert snap['factor_model_version'] == strength.VERSION
assert [x['key'] for x in snap['strategies']] == ['trend']
assert set(snap['radar']) == {'trend'}
assert all(rows[i]['stock_strength_score'] >= rows[i+1]['stock_strength_score'] for i in range(len(rows)-1))
assert sum(snap.get('axis_counts', {}).values()) == len(rows)
assert snap['strength_model']['strength_version'] == stock_strength.VERSION
assert snap['intraday_model']['version'] == intraday.VERSION
assert snap['intraday_model']['rule_version'] == config.INTRADAY_RULE_VERSION
structure=snap.get('wyckoff_structure') or {}
assert structure.get('version') == wyckoff_structure.VERSION
assert structure['count'] == len(structure['rows'])
assert all(r['version'] == wyckoff_structure.VERSION and r['created_asof'] <= r['evidence_asof']
           for r in structure['rows'])
assert 'function structureDetail(code)' in html
if snap.get('intraday_close_confirmation'):
    assert snap['intraday_close_confirmation'].get('model_version') == snap['intraday_model']['version']
    assert snap['intraday_close_confirmation'].get('rule_version') == snap['intraday_model']['rule_version']
assert snap['strength_model']['strength_reference_count'] >= len(rows)
assert snap['strength_model']['core_required_bars'] == strength.CORE_BARS == 25
assert snap['risk_gate']['min_trading_days'] == 25
assert all(r['persistent_strong'] == all(r['persistent_qualification'].values()) for r in rows)
assert sum(s['persistent_strong'] for s in rows) == snap['strength_model']['persistent_strong_count']
assert sum(s['recent_improving'] for s in rows) == snap['strength_model']['recent_improving_count']
assert sum(s['high_fading'] for s in rows) == snap['strength_model']['high_fading_count']
assert (snap.get('market_emotion') or {}).get('limit_up') == snap['breadth']['limit_up'] or snap.get('mode') == 'local-rebuild'
if snap.get('mode') != 'local-rebuild':
    assert sum(x['up'] for x in snap['board_mix'].values()) == snap['breadth']['up']
    assert sum(x['down'] for x in snap['board_mix'].values()) == snap['breadth']['down']
assert not ({x['code'] for x in snap.get('emotion_candidates', [])} & {x['code'] for x in rows})
assert all(x['trend_online'] is None and x['emotion_strong'] for x in snap.get('emotion_candidates', []))
outside = snap['coverage_catalog']
base_outside = [x for x in outside if not x.get('stale_carried')]
assert len(base_outside) == snap['coverage_stats']['excluded']
assert len(base_outside) + len(rows) == snap['risk_gate']['pool_in']
assert not ({x['code'] for x in outside} & {x['code'] for x in rows})
assert len({x['code'] for x in outside}) == len(outside)
assert sum(x['trend_online'] == 1 for x in base_outside) == snap['coverage_stats']['trend_online_outside']
for x in outside:
    assert x['reason_text'] and x['code'] and x['name']
    if x['trend_online'] is not None:
        assert x['signal_date'] == snap['strength_model']['asof']
        assert bool(x['trend_online']) == (x['ma5'] > x['ma10'] > x['ma20'] > x['ma20_prev'] and x['signal_close'] >= x['ma10'])
        if (x.get('trend_basis') == '最近21日均线'
                and x.get('trade_status') not in ('no_trade', 'trade_recovered_wait_daily')):
            assert x['daily_strength_status'] == '趋势可核验、强度待评分'
            assert x.get('stock_strength_score') is None
assert 'amount' not in snap['risk_gate']['dropped']
assert 'min_amount_median_wan' not in snap['risk_gate']
south = next((x for x in rows if x['code'] == '000504'), None)
if south is not None:
    assert south['name'] == '南华生物' and south['trend_online'] == 1
for row in rows:
    assert row['signal_date'] == snap['strength_model']['asof']
    assert row['rank'] >= 1 and 0 <= row['score'] <= 100
    assert row['score'] == row['factors']['rs'] == row['strength_percentile']
    assert row['score'] == row['stock_strength_percentile']
    assert 0 <= row['ret20_percentile'] <= 100
    parts = row['stock_strength_parts']
    assert set(parts) == set(stock_strength.WEIGHTS)
    assert abs(row['stock_strength_score'] - sum(parts[k] * stock_strength.WEIGHTS[k] for k in parts)) < 0.02
    assert 0 <= row['stock_strength_percentile'] <= 100
    assert row['stock_strength_motion'] in ('增强', '维持', '衰减', '修复')
    assert row['stock_strength_display_state'] == ('总体仍强，近期衰减' if row['persistent_strong'] and row['high_fading'] else row['stock_strength_motion'])
    assert row['current_drawdown_pct'] == row['distance_high20_pct']
    assert row['industry_trend_state'] in ('数据不足', '收缩', '持续扩散', '扩散初现', '同行偏弱', '未见扩散')
    assert row['industry_stock_relation'] in ('个股相对领先', '个股落后', '个股相对表现待确认')
    assert row['industry_peer_trend_rising_days2'] is None or 0 <= row['industry_peer_trend_rising_days2'] <= 2
    assert row['theme_assist'] in ('数据不足', '按题材分别查看')
    assert row['theme_assist_name'] is None
    assert {r['name'] for r in row['theme_relations']} == set(row.get('boards', []))
    for relation in row['theme_relations']:
        assert relation['state'] in ('数据不足', '未见扩散', '趋势扩散', '情绪扩散', '趋势与情绪共同扩散')
        if relation['peers'] >= 5 and row['theme_basis'] != '同花顺详情成员待F10核对':
            assert relation['state'] != '数据不足'
    if row['trend_assist'] == '核心独强':
        assert row['stock_strength_percentile'] >= 75 and row['ret5'] > 0 and row['ret20'] > 0 and row['ret5_ex_industry'] >= 2
    assert row['strength_direction'] in ('上涨延续', '上涨中回调', '近期反弹', '相对抗跌', '绝对下跌')
    assert row['path_eff20'] * row['ret20'] >= -0.01
    assert not any(k.startswith(('score_', 'ign_')) for k in row), row['code']
    b = row['industry_breadth']
    if b is not None:
        assert row['industry_peers'] >= config.SIMPLE_STRENGTH['min_industry_peers']
        assert abs(b - row['industry_above20']/row['industry_peers']*100) < 0.011
    assert row['factors']['sector'] == b
    assert bool(row['trend_aligned']) == (row['ma5'] > row['ma10'] > row['ma20'] > row['ma20_prev'])
    assert bool(row['trend_online']) == (bool(row['trend_aligned']) and row['signal_close'] >= row['ma10'])
    assert bool(row['broke20']) == (row['signal_close'] > row['ph20'])
    assert row['watch_candidate'] == bool(row['trend_online'])
    assert row['trend_stage'] in ('日线初步转强', '日线趋势延续', '日线回踩待确认', '日线加速偏离', '日线结构转弱', '日线趋势未成立')
    assert row['axis_group'] in ('情绪活跃·趋势在线', '情绪活跃·趋势未在线', '趋势在线·情绪平稳', '趋势未在线·情绪平稳', '情绪数据不足')
    assert row['trend_assist'] and row['emotion_assist'] and row['roles']
    if snap.get('mode') != 'local-rebuild' and row.get('emotion_peer_count'):
        assert 'emotion_peer_yesterday_limit' in row
    assert not ({'龙头', '跟随股'} & set(row['roles']))
    assert row['entry_watch'] == bool(row['current_pullback_candidate'])
    if row['current_pullback_candidate']:
        assert all(row['current_pullback_qualification'].values())
        assert row['intraday_phase_status'] in ('早盘', '午盘', '尾盘')
        assert row['intraday_quote_fresh'] is True
        assert row['historical_pullback_shape'] is True
        assert row['price'] >= row['intraday_ma10']
        assert not row['intraday_serious_weakness'] and not row['overheated']
        assert not row['intraday_trade_restriction']
    if row.get('intraday_score') is not None:
        assert (row.get('intraday_score_available_components') == 3
                or (row.get('intraday_score_stale') is True
                    and row.get('intraday_quote_fresh') is False))
    if row.get('intraday_price_basis_comparable') is False:
        assert row.get('intraday_ma10') is None and row.get('intraday_ma20') is None
        assert not row.get('current_strong_candidate') and not row.get('current_pullback_candidate')
    if row.get('current_strong_candidate'):
        assert row.get('current_strong_qualification')
        assert all(row['current_strong_qualification'].values())
        assert row.get('intraday_prior_daily_trend_online') == 1
        assert row.get('intraday_trend_ok') is True
        assert row.get('change_pct') > 0
        assert row.get('intraday_relative_return_pct') > 0
        assert row.get('price') >= row.get('open')
        assert row.get('intraday_score_available_components') == 3
        assert '触板未封' not in row.get('intraday_risk_flags', [])
    if row.get('startup_candidate'):
        assert all(row['startup_qualification'].values())
        assert row['intraday_observation_state'] == '初步转强，待收盘确认'
        assert row.get('intraday_prior_daily_trend_online') == 0
        assert row.get('intraday_score') is not None
        assert row.get('intraday_quote_fresh') is True
    if row['intraday_quote_fresh'] is not True:
        assert not row['current_strong_candidate'] and not row['current_pullback_candidate']
        if row.get('intraday_observation_available') is True:
            assert snap['session'] == '午间休市'
            assert row['intraday_judgment_at'] == snap['quote_capture_at'][:10]+' 11:30:00'
            assert row['intraday_score_stale'] is False
            assert row['intraday_risk_level'] != '未知'
            assert row['intraday_path']['last_at'] == row['intraday_judgment_at']
            assert row['intraday_path']['distinct_count'] <= row['intraday_path']['acquired_count']
            assert not row.get('attack_watch_candidate')
        else:
            if snap['session'] in ('集合竞价','竞价结束'):
                assert row['intraday_risk_level'] == '待核验'
                assert row['intraday_price_basis_comparable'] is False
                assert not row.get('intraday_risk_flags')
            else:
                assert row['intraday_risk_level'] == '未知'
            assert row['intraday_score'] is None or row['intraday_score_stale'] is True
    if row['fund_positive_all'] is not None:
        assert row['fund_asof'] == row['signal_date']
        assert row['fund_positive_all'] == all(row[f'fund{n}_yi'] > 0 for n in (3, 5, 10))
        assert row.get('fund_history_source')
    if row.get('fund_today_yi') is not None:
        assert row.get('fund_today_source') == snap['fund_source']
        assert row.get('fund_today_at') == snap['fund_meta'].get('fetched_at')
        assert row.get('fund_today_at') is not None
for row in outside:
    if row.get('fund_today_yi') is not None:
        assert row.get('fund_today_source') == snap['fund_source']
        assert row.get('fund_today_at') == snap['fund_meta'].get('fetched_at')
        assert row.get('fund_today_at') is not None
for item in snap['radar']['trend']['items']:
    assert len(item['f']) == 1
    assert item['strong']
for tier in radar.tiers():
    expected = sorted((r for r in rows if r.get('trend_tier') == tier['key']),
                      key=lambda r: (r['trend_pool_rank'], r['code']))[:config.RADAR['show_per_tier']]
    actual = [x for x in snap['radar']['trend']['items'] if x['tier'] == tier['key']]
    assert [x['code'] for x in actual] == [r['code'] for r in expected], f"雷达 {tier['key']} 档未截取最强名单"

catalog = snap['board_catalog']
ids = {b['id'] for b in catalog}
assert len(ids) == len(catalog)
assert 'theme:专精特新' not in ids
stock_by_code = {s['code']: s for s in rows}
for board in catalog:
    assert board['ranking_eligible'] == (board['valid_members'] >= config.SIMPLE_STRENGTH['min_industry_peers'] + 1)
    assert (board['trend_rank'] is not None) == board['ranking_eligible']
    assert board['lists']['trend'] == [r['code'] for r in board['members'] if stock_by_code[r['code']]['persistent_strong']]
    assert set(board['lists']['recent']) == {r['code'] for r in board['members'] if stock_by_code[r['code']]['recent_improving']}
    assert board['type'] in ('industry', 'theme')
    assert len(board['members']) == board['valid_members']
    assert set(board['member_codes']) >= {r['code'] for r in board['members']}
    assert [r['score'] for r in board['members']] == sorted((r['score'] for r in board['members']), reverse=True)
    assert board['fund_sum_5d'] is not None or board['fund_covered'] == 0
    assert board['fund_sum_today'] is not None or board['fund_today_covered'] == 0
    if board['detail_members_cached'] is not None and board['detail_members_cached'] < board['pool_members']:
        assert not board['source_complete']
        assert board['source_members'] == board['pool_members']
    if not board['source_complete']:
        assert board['source_scope'] == '本系统主板池'
    for r in board['members']:
        s = stock_by_code[r['code']]
        assert r['global_rank'] == s['stock_strength_rank']
        assert r['score'] == s['stock_strength_score']
        if board['type'] == 'theme':
            assert board['name'] in (s.get('display_boards') or s.get('boards') or [])
        if r['excess5'] is not None:
            assert board['valid_members'] >= 6
    for key in ('trend', 'recent', 'emotion'):
        assert set(board['lists'][key]) <= {r['code'] for r in board['members']}
for board in snap['boards']:
    assert board['fund'] is None or board['fund_src'] != '未知'
    assert board['name'] != '专精特新'
if snap['fund_meta'].get('period') == 'today':
    assert '超大单' in snap['fund_source']
    assert all(b['fund_covered'] == 0 for b in catalog)
assert sum(snap['fund_confirmation'].get('source_counts', {}).values()) == snap['fund_confirmation']['covered']
assert sum(t['n'] for t in snap['radar']['trend']['tiers']) == sum(bool(r['watch_candidate']) for r in rows)
for ident in ['seg','tb-stocks','tb-radar','tb-boards','tb-themes','tb-hold','drawer','btn-refresh','work-attack-list','work-consolidation-pending','work-close-table','ov-axes','ov-market-emotion','ov-emotion-only']:
    assert f'id="{ident}"' in html, ident
assert 'id="work-trend-comparison"' not in html
assert 'function uiTrendPullbackItems(s)' in html and 'id="stock-trend-pullbacks"' in html
assert 'data-s="ignition"' not in html
assert "STATE.filters.states=['watch']" not in html
assert '清除搜索与筛选，查看全部样本' in html and '相对评分变化' in html
assert 'function currentCandidateQuoteUsable(s)' in html
assert "currentCandidateActive(s,'current_pullback_candidate')" in html
assert 'setInterval(refreshPageFreshness,60000)' in html
assert html.count('var PRESETS=') == 1
print(f"OK: {len(rows)} stocks; daily={snap['strength_model']['asof']}; intraday={snap['intraday_model']['asof']}; trend, risk and UI contract valid")
