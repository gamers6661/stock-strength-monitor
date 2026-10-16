"""现有日线的描述性核对：趋势在线与回踩反弹，统一次日开盘/10日退出。"""
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import config
import strength
from replay_strength import local_data, trade_path


def run():
    _, series = local_data()
    calendar = strength.trading_calendar(series)
    indexed = {c: {b["date"]: b for b in bars} for c, bars in series.items()}
    events = defaultdict(list)
    held_until = defaultdict(dict)
    for t in range(60, len(calendar) - 10):
        wanted = calendar[t - 60:t + 1]
        for code, bars in indexed.items():
            window = [bars.get(d) for d in wanted]
            if any(b is None for b in window):
                continue
            m = strength.day_metrics(window)
            if not m:
                continue
            groups = ["趋势在线"] if m["trend_online"] else []
            if m["trend_online"] and m["touch_state"] in ("回踩反弹", "回踩后上行"):
                groups.append("回踩反弹")
            for group in groups:
                if held_until[group].get(code, -1) >= t:
                    continue
                trade = trade_path(bars, calendar, t)
                if trade["status"] != "closed":
                    continue
                events[group].append(trade["net_pct"])
                held_until[group][code] = trade["exit_index"]
    lines = ["# 均线趋势与回踩：近期描述性核对", "",
             f"信号日 {calendar[60]} 至 {calendar[-11]}；使用当前股票池与已有日线。", "",
             "同一股票同一组持有期内不重复入样；次日开盘买入，固定第10个交易日收盘退出，若一字跌停无法退出则顺延；假设往返费用与滑点合计0.30%。", "",
             "| 观察组 | 完成事件 | 平均净收益 | 净胜率 |", "|---|---:|---:|---:|"]
    for label in ("趋势在线", "回踩反弹"):
        values = events[label]
        lines.append(f"| {label} | {len(values)} | {sum(values)/len(values):+.2f}% | {sum(v>0 for v in values)/len(values)*100:.1f}% |" if values
                     else f"| {label} | 0 | — | — |")
    lines += ["", "两组事件有交集，不是可直接比较的独立组合；资金3/5/10日条件未参与，因为没有完整时点历史。",
              "当前股票池有幸存者偏差；日线长度短、事件窗口重叠、历史ST身份未知，日线也不能证明实际成交。这里不做显著性判断或仓位收益推断。",
              "当前样本未支持把‘盘中触及MA10、收盘站回并上行’直接作为买入信号；页面仅作观察标记。", ""]
    output = Path(__file__).with_name("近期核对.md")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    run()
