"""个股强度V3：回放前冻结的研究初值；分数不表示收益概率。"""
VERSION = '个股强度V3-20261029.1'
RULES = dict(
    periods=[5, 10, 20], period_weights=[.40, .35, .25],
    return_scales=[8., 12., 20.], excess_scales=[6., 8., 12.],
    weights=dict(price=.45, relative=.30, volume=.25),
    min_bars=26, market_coverage=.80, min_peers=6, peer_coverage=.80,
    strong_score=65., price_floor=60., advance_min=[3., 5., 8.],
    breakout_atr=.2, breakout_volume=1.3, breakout_clv=.7,
    pullback_max_atr=2.5, retrace_max=.5, support_buffer_atr=.3,
    recent_strong_days=10, amount_min=20000000.,
    repair_return5=5., repair_excess5=3., repair_up_days=3,
    repair_volume_ratio=1.2, repair_clv=.6, repair_drawdown_atr=1.5,
    live_hold_seconds=240, live_hold_samples=3, live_gap_seconds=180,
    live_volume_ratio=1.3, max_quote_age_seconds=600,
    live_weak_pct=-3., same_time_reference_days=5, same_time_tolerance_seconds=60,
)

QUALITY = dict(version="推进质量20261029.1", confirmation_days=3, concentration_floor=.35,
    impulse_discount_max=.5, retention_days=5, local_retention_weight=.7,
    excess_volume_full=3., volume_half_life=3., volume_pressure_penalty=.25,
    pressure_days=3, pressure_decay=.5, price_damage_max=.3)
