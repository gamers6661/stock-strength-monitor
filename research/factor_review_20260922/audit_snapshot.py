"""Read-only factor audit; preserve one snapshot, never refresh live data."""
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
frozen = OUT / "snapshot_frozen.json"
if not frozen.exists():
    frozen.write_bytes((ROOT / "cache/snapshot.json").read_bytes())
snap = json.loads(frozen.read_text(encoding="utf-8"))
rows = snap["stocks"]

def ranks(vals):
    order = sorted(range(len(vals)), key=vals.__getitem__)
    result = [0.0] * len(vals)
    i = 0
    while i < len(vals):
        j = i + 1
        while j < len(vals) and vals[order[j]] == vals[order[i]]:
            j += 1
        for k in range(i, j):
            result[order[k]] = (i + j - 1) / 2
        i = j
    return result

def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    x, y = zip(*pairs)
    x, y = ranks(x), ranks(y)
    mx, my = statistics.mean(x), statistics.mean(y)
    denominator = math.sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y)) / denominator, 4) if denominator else None

stats = {
    "generated_at": snap["generated_at"],
    "snapshot_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
    "session": snap["session"],
    "n": len(rows),
    "weights": snap["strategy_weights"],
    "breadth": snap["breadth"],
    "factor_spearman": {},
    "top20": {},
}
keys = ["rs", "pv", "trend", "sector", "sent", "crowd"]
for a in keys:
    stats["factor_spearman"][a] = {
        b: corr([s["factors"].get(a) for s in rows],
                [s["factors"].get(b) for s in rows]) for b in keys
    }
for key in ["score", "score_short", "score_mid", "score_trend", "ign_score"]:
    top = sorted([s for s in rows if s.get(key) is not None], key=lambda s: -s[key])[:20]
    stats["top20"][key] = {
        "n": len(top),
        "dist_atr_gt_3_5": sum(s["dist_atr"] > 3.5 for s in top),
        "dist_atr_gt_5": sum(s["dist_atr"] > 5 for s in top),
        "crowd_lt_40": sum(s["factors"]["crowd"] < 40 for s in top),
        "limit_today": sum(bool(s["limit_today"]) for s in top),
        "clv_lt_0_4": sum(s["clv"] < 0.4 for s in top),
        "fake_lt_60": sum((s.get("ign_factors") or {}).get("fake", 100) < 60 for s in top),
        "median_ret5": round(statistics.median(s["ret5"] for s in top), 2),
        "stocks": [{k: s.get(k) for k in ["code", "name", key, "dist_atr", "clv", "ign_factors"]} for s in top],
    }
stats["score_short_mid_spearman"] = corr([s["score_short"] for s in rows], [s["score_mid"] for s in rows])
short = {s["code"] for s in sorted(rows, key=lambda s: -s["score_short"])[:20]}
mid = {s["code"] for s in sorted(rows, key=lambda s: -s["score_mid"])[:20]}
stats["short_mid_top20_overlap"] = len(short & mid)
ign = [s for s in rows if s.get("ign_pass")]
stats["ignition"] = {
    "n": len(ign),
    "clv_lt_0_4": sum(s["clv"] < 0.4 for s in ign),
    "fake_lt_60": sum(s["ign_factors"]["fake"] < 60 for s in ign),
    "negative_breakout_pct": sum(s["brk_pct"] < 0 for s in ign),
    "age_distribution": dict(Counter(s["breakout_age"] for s in ign)),
}
stats["missing_sector"] = sum(s["factors"].get("sector") is None for s in rows)
history = [json.loads(x) for x in (ROOT / "cache/history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
stats["history"] = {"rows": len(history), "days": sorted({x["ts"][:10] for x in history}), "fields": list(history[-1])}
con = sqlite3.connect((ROOT / "cache/market.db").as_uri() + "?mode=ro", uri=True)
coverage = []
for s in rows:
    code = s["code"]
    dates = [r[0] for r in con.execute("SELECT date FROM kline WHERE code=? ORDER BY date", (code,))]
    coverage.append((code, len(dates), dates[0], dates[-1]))
stats["scored_pool_db"] = {"median_bars": statistics.median(x[1] for x in coverage), "latest_date_counts": dict(Counter(x[3] for x in coverage)), "earliest_start": min(x[2] for x in coverage)}
con.close()
(OUT / "audit_metrics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
compact = {**stats, "top20": {k: {a: b for a, b in v.items() if a != "stocks"} for k, v in stats["top20"].items()}}
print(json.dumps(compact, ensure_ascii=False, indent=2))
