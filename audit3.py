# -*- coding: utf-8 -*-
"""审计 3：扫描快照中的异常值 + 题材标签质量 + 无成交样本"""
import json
from collections import Counter

import config

S = json.load(open("cache/snapshot.json", encoding="utf-8"))

print("=" * 96)
print("A. 快照元信息")
print("=" * 96)
for k in ("generated_at", "mode", "session", "pool_size", "stock_count",
          "fund_source", "fund_available", "em_status", "elapsed"):
    print(f"  {k:<18} = {S.get(k)}")
print(f"  数据已过去 {len(S.get('boards', []))} 个板块 / {len(S.get('stocks', []))} 只个股")

print()
print("=" * 96)
print("B. 个股字段异常扫描")
print("=" * 96)


def scan(label, fn, expect):
    bad = [s for s in S["stocks"] if not expect(fn(s))]
    print(f"  {label:<34} 异常 {len(bad):>5} 只", end="")
    if bad:
        ex = bad[:3]
        print("  例: " + ", ".join(f"{x['name']}({x['code']})={fn(x)}" for x in ex))
    else:
        print()


scan("涨跌幅 |x| > 21%（主板不可能）", lambda s: s.get("change_pct"),
     lambda v: v is not None and abs(v) <= 21)
scan("综合分超出 [0,100]", lambda s: s.get("score"), lambda v: v is not None and 0 <= v <= 100)
scan("因子分超出 [0,100]", lambda s: (s.get("factors") or {}).get("rs"),
     lambda v: v is None or 0 <= v <= 100)
scan("量比(5日) > 30", lambda s: s.get("vol_ratio5"), lambda v: v is not None and v <= 30)
scan("换手率 > 60%", lambda s: s.get("turnover"), lambda v: v is not None and v <= 60)
scan("ret5 超出 ±80%", lambda s: s.get("ret5"), lambda v: v is not None and abs(v) <= 80)
scan("position60 超出 [0,100]", lambda s: s.get("position60"),
     lambda v: v is not None and 0 <= v <= 100)
scan("价格 <= 0", lambda s: s.get("price"), lambda v: v is not None and v > 0)
scan("暂无当日成交（涨跌=0）", lambda s: s.get("change_pct"), lambda v: v != 0)

print()
print("=" * 96)
print("C. 极值观察（判断是否仍有口径失真）")
print("=" * 96)
top = sorted(S["stocks"], key=lambda s: -(s.get("vol_ratio5") or 0))[:8]
print("  量比(5日) 最高 8 只：")
for s in top:
    print(f"    {s['name']:<9}{s['code']} 量比{s['vol_ratio5']:>7.2f}  今日{s['change_pct']:>+6.2f}%"
          f"  换手{s.get('turnover'):>5.2f}%  盘中bar={s.get('vol_partial')}")
top = sorted(S["stocks"], key=lambda s: -(s.get("turnover") or 0))[:5]
print("  换手率 最高 5 只：")
for s in top:
    print(f"    {s['name']:<9}{s['code']} 换手{s['turnover']:>6.2f}%  今日{s['change_pct']:>+6.2f}%")

print()
print("=" * 96)
print("D. 题材标签质量（是否混入非题材的属性标签）")
print("=" * 96)
cnt = Counter()
for s in S["stocks"]:
    for b in (s.get("boards") or []):
        cnt[b] += 1
print(f"  出现的标签总数 {len(cnt)}，TOP 30：")
for t, c in cnt.most_common(30):
    print(f"    {t:<22} {c}")
noise_kw = ["融资融券", "沪股通", "深股通", "标普", "MSCI", "富时", "破发", "次新",
            "昨日", "涨停", "低价股", "高价股", "预盈", "预增", "回购", "解禁",
            "国企改革", "央企", "国资", "参股", "创投", "注册制", "专精特新", "转债"]
hit = [(t, c) for t, c in cnt.most_common() if any(k in t for k in noise_kw)]
print(f"\n  疑似噪音标签 {len(hit)} 个：")
for t, c in hit[:25]:
    print(f"    {t:<22} {c}")

print()
print("=" * 96)
print("E. 板块榜口径分布")
print("=" * 96)
print(f"  {'板块':<20}{'资金口径':<20}{'联动口径':<22}{'评分':>7}")
print("-" * 96)
for b in S["boards"][:20]:
    print(f"  {b['name'][:18]:<20}{str(b.get('fund_src'))[:18]:<20}"
          f"{str(b.get('linkage_src'))[:20]:<22}{b['score']:>7.2f}")

src = Counter(b.get("fund_src") for b in S["boards"])
print(f"\n  资金口径分布：{dict(src)}")

print()
print("=" * 96)
print("F. 板块资金覆盖 vs 题材组覆盖")
print("=" * 96)
tr = S.get("theme_rank") or []
print(f"  题材组榜条数 {len(tr)}")
if tr:
    for r in tr[:6]:
        print(f"    {r['name']:<18} 成员{r['n']:>4} 上涨占比{r['up_ratio']:>6.1f}% 等权{r['avg_chg']:>+6.2f}%")
print(f"  theme_index 条目 {len(S.get('theme_index') or {})}")
