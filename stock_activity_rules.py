"""个股页独立规则。首轮冻结于回放之前，不按当日名单调参。"""
VERSION = '个股主动强度V2.1-20261020.4'
SCORE_VERSION = 'LHEQ-R关闭-20261019.2'
RULES = dict(
    candidate_boards=['sh_main', 'sz_main'], min_history=21,
    min_median_amount_yuan=20000000., min_peers=8, coverage_min=.8,
    gap_max=180, quote_age_max=600, window_seconds=360, window_tolerance=60,
    min_samples=4, source_skew_max=60, quote_clock_error_max=5, min_push_pct=.5, tick_size=.01, tick_multiple=3.,
    noise_atr_multiple=1.5, session_seconds=14400., excess_min_pp=.10,
    confirm_seconds=240, confirm_samples=2, hold_min=.60, fail_hold=.35,
    fail_samples=2, role_wait_seconds=600, diffusion_fraction=.30,
    peer_start_fraction=.20, peer_start_min=3, role_horizon_seconds=1800,
    event_seconds=1800, rearm_seconds=600, rearm_atr=.25,
    identity_break_atr=.3, identity_loss_samples=3, identity_loss_seconds=240,
    identity_lead_floor_pp=-1., identity_attention_min=.5,
    independent_events=2, independent_span_seconds=1200,
    core_attention_ratio_min=1., history_half_life=5., excess_scale=5.,
    intraday_excess_weight=.25, intraday_excess_cap_pp=2.,
    reference_gain5_pct=6., reference_atr_multiple=2., effective_pushes_min=1.6,
    attention_ratio_cap=3., history_events_days=20, stored_events=12,
    enabled_factors=['L', 'H', 'E', 'Q'],
    weights_core=dict(L=30., H=20., E=20., Q=20.),
    weights_start=dict(L=40., H=10., E=20., Q=20.),
    R_enabled=False,
)
