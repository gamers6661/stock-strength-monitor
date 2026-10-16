"""当前股票池的短样本描述回放；只比较排序，不优化参数或推断可交易收益。"""
from collections import Counter
from pathlib import Path
from statistics import mean, median

import config
import replay_strength
import stock_strength
import strength


OUT = Path(__file__).with_name("短样本排序对照.md")


def summarize(days):
    if not days:
        return "无可比较样本"
    return (f"{len(days)}日；日均净收益 {mean(days):+.2f}%；"
            f"中位数 {median(days):+.2f}%；正收益日 {sum(x > 0 for x in days) / len(days):.0%}")


def run():
    _, series = replay_strength.local_data()
    calendar = strength.trading_calendar(series)
    index = {c: {b["date"]: i for i, b in enumerate(bars)} for c, bars in series.items()}
    by_date = {c: {b["date"]: b for b in bars} for c, bars in series.items()}
    variants = ["20日涨幅", "四项强度"] + [f"去掉{stock_strength.LABELS[k]}" for k in stock_strength.WEIGHTS]
    outcomes = {h: {v: [] for v in variants} for h in (5, 10)}
    paired = {h: [] for h in (5, 10)}
    cohorts = 0
    skipped = Counter()
    overlaps = []
    volatility_recovery = {group: [] for group in ("低波动", "中波动", "高波动")}
    for t in range(60, len(calendar) - 10):
        date = calendar[t]
        wanted = calendar[t - 60:t + 1]
        windows = {}
        metrics = {}
        for code, bars in series.items():
            end = index[code].get(date)
            if end is None or end < 60:
                continue
            window = bars[end - 60:end + 1]
            if [bar["date"] for bar in window] != wanted:
                continue
            data = strength.day_metrics(window)
            if data:
                windows[code], metrics[code] = window, data
        own, _ = stock_strength.score(metrics, {c: {} for c in metrics}, windows)
        candidates = [c for c in own if metrics[c]["trend_online"]]
        if len(candidates) < 20:
            continue
        cohorts += 1
        rankings = {"20日涨幅": sorted(candidates, key=lambda c: (-metrics[c]["ret20"], c))[:20],
                    "四项强度": sorted(candidates, key=lambda c: (-own[c]["stock_strength_score"], c))[:20]}
        for removed in stock_strength.WEIGHTS:
            def subtotal(code):
                parts = own[code]["stock_strength_parts"]
                return sum(parts[k] * weight for k, weight in stock_strength.WEIGHTS.items()
                           if k != removed) / (1 - stock_strength.WEIGHTS[removed])
            rankings[f"去掉{stock_strength.LABELS[removed]}"] = sorted(
                candidates, key=lambda c: (-subtotal(c), c))[:20]
        overlaps.append(len(set(rankings["20日涨幅"]) & set(rankings["四项强度"])))
        # 验证回撤修复分在不同波动组的增量方向；同日组内配对，不据此调权重。
        for group in volatility_recovery:
            peers = [c for c in candidates if own[c]["volatility_group"] == group]
            if len(peers) < 10:
                continue
            peers.sort(key=lambda c: (own[c]["stock_strength_parts"]["recovery"], c))
            half = len(peers) // 2
            low, high = peers[:half], peers[-half:]
            def next_five(codes):
                values = [replay_strength.trade_path(by_date[c], calendar, t, horizon=5)
                          for c in codes]
                return [v["net_pct"] for v in values if v["status"] == "closed"]
            lo, hi = next_five(low), next_five(high)
            if len(lo) >= 5 and len(hi) >= 5:
                volatility_recovery[group].append(mean(hi) - mean(lo))
        for horizon in (5, 10):
            for variant, codes in rankings.items():
                realized = []
                for code in codes:
                    result = replay_strength.trade_path(by_date[code], calendar, t, horizon=horizon)
                    if result["status"] == "closed":
                        realized.append(result["net_pct"])
                    else:
                        skipped[result["status"]] += 1
                if realized:
                    outcomes[horizon][variant].append((date, mean(realized)))
            current = dict(outcomes[horizon]["四项强度"])
            prior = dict(outcomes[horizon]["20日涨幅"])
            if date in current and date in prior:
                paired[horizon].append(current[date] - prior[date])
    lines = ["# 个股强度短样本排序对照", "",
             "仅用当前股票池及本机现存日线，完成日线形成信号、次日开盘入场、固定5/10交易日收盘退出；扣除0.30%假设成本。每个判断日趋势在线股分别取前20名，不调权重或阈值。", "",
             f"回放判断日 {cohorts} 个；两种前20名单平均重合 {mean(overlaps):.1f} 只。买不到或数据不足的记录：{dict(skipped)}。", ""]
    for horizon in (5, 10):
        lines += [f"## 持有 {horizon} 个交易日", ""]
        for variant in variants:
            lines.append(f"- {variant}：{summarize([v for _, v in outcomes[horizon][variant]])}")
        diff = paired[horizon]
        lines.append(f"- 四项强度减20日涨幅，同日配对差：{summarize(diff)}")
        mid = len(diff) // 2
        lines.append(f"- 前半段配对差：{summarize(diff[:mid])}；后半段：{summarize(diff[mid:])}")
        lines.append("")
    lines += ["## 解释边界", "",
              "当前股票池回看历史存在幸存者偏差；行业归属不使用历史时点记录。本版进攻分不含行业超额，回放中不影响分数，但行业助攻无法用它验证。",
              "逐日形成的持有期严重重叠，上述正收益日和均值只是描述，不能按独立样本推算显著性；未做仓位、容量或真实滑点模拟。",
              "这段本机日线只覆盖近期市场，不能代表不同市场阶段。若四项强度及删项比较没有稳定优势，不应据此调整权重或宣称有效。",
              "真实上线后的每日强度记录另行积累；前日/前五日分位变化不能用此回放补造。", ""]
    lines += ["## 回撤修复分的波动分组检查", "",
              "每个判断日先按ATR/收盘价分位切成低/中/高三组，再在组内比较回撤修复分上半与下半，固定5日净收益。此处只检验方向，不调权重；逐日样本重叠，不作显著性结论。", ""]
    for group, differences in volatility_recovery.items():
        lines.append(f"- {group}：高修复减低修复 {summarize(differences)}")
    lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(str(OUT))
    print("cohorts", cohorts, "overlap", round(mean(overlaps), 2) if overlaps else None)


if __name__ == "__main__":
    run()
