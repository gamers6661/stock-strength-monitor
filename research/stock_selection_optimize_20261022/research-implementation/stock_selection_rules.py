"""个股强度V3：回放前冻结的研究初值；分数不表示收益概率。"""
VERSION = '个股强度V3-20261022.5'
RULES = dict(
    periods=[5, 10, 20], period_weights=[.40, .35, .25],
    return_scales=[8., 12., 20.], excess_scales=[6., 8., 12.],
    weights=dict(price=.45, relative=.30, volume=.25),
    min_bars=26, market_coverage=.80, min_peers=6, peer_coverage=.80,
    strong_score=65., price_floor=60., advance_min=[3., 5., 8.],
    breakout_atr=.2, breakout_volume=1.3, breakout_clv=.7,
    pullback_max_atr=2.5, retrace_max=.5, support_buffer_atr=.3,
    recent_strong_days=10, amount_min=20000000.,
    live_hold_seconds=240, live_hold_samples=3, live_gap_seconds=180,
    live_volume_ratio=1.3, max_quote_age_seconds=600,
    live_weak_pct=-3., same_time_reference_days=5, same_time_tolerance_seconds=60,
)
