"""离线迁移已有快照；不抓取行情、不更改原报价时间。"""
from datetime import datetime
import json

import config
import emotion
import price_only
import make_dashboard
import radar
import report
import scoring
import strength
import attack_model
from replay_strength import local_data


def run():
    snap = json.loads(config.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    price_only.sanitize(snap)
    pool, series = local_data()
    profiles = json.loads((config.CACHE_DIR / "ths_stock_profiles.json").read_text(encoding="utf-8")).get("profiles", {})
    members = json.loads((config.CACHE_DIR / "ths_industry_members.json").read_text(encoding="utf-8")).get("map", {})
    if not snap.get("fund_available"):
        for s in snap["stocks"]:
            s["factors"] = {"fund": None}
    rows, meta = strength.build(snap["stocks"], series, strength.industry_map(profiles, members))
    if not rows:
        raise RuntimeError("本地重建无有效个股；未覆盖快照")
    snap["market_emotion"] = {"state": "离线未核验", "scope": "需要全池当时报价才能重建情绪"}
    snap["emotion_candidates"] = []
    emotion.enrich_stocks(rows, {}, {"active_count": 0, "traded": 0})
    snap["axis_counts"] = {"情绪数据不足": len(rows)}
    snap.update(stocks=rows, stock_count=len(rows), strength_model=meta,
                factor_model_version=strength.VERSION, mode="local-rebuild",
                rebuilt_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategies=config.STRATEGY["list"], strategy_factors=config.STRATEGY["factors"],
                strategy_weights=config.STRATEGY_WEIGHTS, default_strategy="trend",
                radar={"trend": radar.build_trend(rows)}, alerts=strength.breakout_alerts(rows))
    snap.pop("ignition_meta", None)
    snap.pop("execution", None)
    snap["risk_gate"].update(passed=len(rows), min_trading_days=strength.CORE_BARS, completed_day_dropped=meta["dropped"])
    snap["board_chain"] = scoring.build_board_chain(snap.get("boards", []), rows)
    snap["board_mix"] = scoring.board_mix({}, rows)
    snap["daily_advice"] = strength.daily_advice(snap)
    # 离线迁移只核验完成日线，不能保留旧版盘中进攻结论为新信号。
    attack_model.enrich(snap, {}, {})
    price_only.sanitize(snap)
    config.atomic_write_text(config.SNAPSHOT_JSON, json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
    strength.save_observation(snap)
    scoring.append_history(snap)
    make_dashboard.build()
    config.atomic_write_text(config.ROOT / "snapshot_report.md", report.build(snap))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run()
