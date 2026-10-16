# -*- coding: utf-8 -*-
"""审计 2：字段语义确认（总市值 vs 流通市值）+ 涨跌家数口径 + K线复权抽查"""
import json
import urllib.parse
import sqlite3

import config
import datafeed as df

# A+H 或流通≠总股本的样本，用于区分腾讯 [44]/[45] 语义
SAMPLE = ["600519", "601398", "601857", "600036", "002594",
          "000001", "601138", "002230", "000725", "601899"]


def em_one(code):
    secid = ("1." if code[0] in "69" else "0.") + code
    fields = ("f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f116,f117,"
              "f162,f163,f164,f167,f168,f169,f170")
    url = "https://push2delay.eastmoney.com/api/qt/stock/get?" + urllib.parse.urlencode({
        "secid": secid, "fltt": "2", "invt": "2", "fields": fields})
    d = json.loads(df.http_get(url, headers={"Referer": "https://quote.eastmoney.com/"}))
    return d.get("data") or {}


def main():
    tq = df.tencent_quotes(SAMPLE)

    print("=" * 108)
    print("A. 市值字段语义：腾讯 [44] / [45]  vs  东财 f117(流通) / f116(总)")
    print("=" * 108)
    print(f"{'代码':<8}{'名称':<10}{'腾讯[44]':>12}{'腾讯[45]':>12}"
          f"{'东财流通(亿)':>14}{'东财总(亿)':>13}   [44]判定        [45]判定")
    print("-" * 108)
    ok44_float = ok45_float = 0
    for c in SAMPLE:
        t = tq.get(c)
        e = em_one(c)
        if not t or not e:
            print(f"{c} 缺数据 腾讯={bool(t)}")
            continue
        v44, v45 = t.get("mcap_yi"), t.get("float_mcap_yi")
        f117 = (e.get("f117") or 0) / 1e8   # 流通市值(亿)
        f116 = (e.get("f116") or 0) / 1e8   # 总市值(亿)

        def judge(v, target):
            if not target or not v:
                return "-"
            return "流通" if abs(v - f117) / f117 < abs(v - f116) / (f116 or 1) else "总"

        j44, j45 = judge(v44, f117), judge(v45, f117)
        if j44 == "流通":
            ok44_float += 1
        if j45 == "流通":
            ok45_float += 1
        print(f"{c:<8}{t['name']:<10}{v44:>12.1f}{v45:>12.1f}"
              f"{f117:>14.1f}{f116:>13.1f}   [{44}]={j44:<6}  [{45}]={j45}")

    print()
    print(f"  结论：[44] 是流通市值的样本数={ok44_float}/{len(SAMPLE)}  "
          f"[45] 是流通市值的样本数={ok45_float}/{len(SAMPLE)}")
    print(f"  代码当前写法: mcap_yi=[44], float_mcap_yi=[45]")

    print()
    print("=" * 112)
    print("B. 其他字段复核（腾讯 vs 东财）")
    print("=" * 112)
    print(f"{'代码':<8}{'字段':<14}{'腾讯':>16}{'东财':>18}{'偏差':>10}")
    print("-" * 112)
    for c in SAMPLE:
        t, e = tq.get(c), em_one(c)
        if not t or not e:
            continue
        pairs = [
            ("现价", t["price"], e.get("f43")),
            ("涨跌幅%", t["change_pct"], e.get("f170")),
            ("成交量(手)", t["volume_shou"], e.get("f47")),
            ("成交额(万元)", t["amount_wan"], (e.get("f48") or 0) / 1e4),
            ("换手率%", t["turnover_pct"], e.get("f168")),
            ("量比", t["vol_ratio"], e.get("f50")),
            ("振幅%", t["amplitude_pct"], None),
        ]
        for label, a, b in pairs:
            if b is None or not b:
                continue
            rel = abs(float(a) - float(b)) / abs(float(b)) * 100
            mark = "" if rel <= 2 else "  <<< 偏差"
            print(f"{c:<8}{label:<14}{float(a):>16.4f}{float(b):>18.4f}{rel:>9.2f}%{mark}")

    print()
    print("=" * 108)
    print("C. 涨跌家数口径（当前实现：仅统计股票池内 = 沪深主板）")
    print("=" * 108)
    pool = df.build_pool()
    print(f"  股票池 {len(pool)} 只（沪深主板）")
    up = sum(1 for q in pool.values() if (q.get("change_pct") or 0) > 0)
    dn = sum(1 for q in pool.values() if (q.get("change_pct") or 0) < 0)
    fl = len(pool) - up - dn
    print(f"  池内 上涨={up} 下跌={dn} 平盘={fl}")
    limit = sum(1 for q in pool.values() if (q.get("change_pct") or 0) >= 9.8)
    print(f"  池内 涨停(>=9.8%)={limit}")
    print("  ⚠ 注意：这是「沪深主板」口径，不等于全市场（不含创业板/科创板/北交所）")

    print()
    print("=" * 108)
    print("D. K线复权抽查（找除权跳空）")
    print("=" * 108)
    conn = sqlite3.connect(config.KLINE_DB)
    bad = 0
    checked = 0
    codes = list(pool.keys())[:400]
    for c in codes:
        rows = conn.execute("SELECT date,open,close FROM kline WHERE code=? ORDER BY date", (c,)).fetchall()
        if len(rows) < 30:
            continue
        checked += 1
        for i in range(1, len(rows)):
            prev_c, cur_o = rows[i - 1][2], rows[i][1]
            if prev_c and cur_o:
                gap = (cur_o / prev_c - 1) * 100
                # 开盘相对昨收跳空超过 25% 且非涨跌停，疑似未复权
                if abs(gap) > 25:
                    bad += 1
                    if bad <= 5:
                        print(f"  疑似跳空 {c} {rows[i][0]}: 昨收{prev_c:.2f} -> 今开{cur_o:.2f} ({gap:+.1f}%)")
                    break
    print(f"  抽查 {checked} 只，疑似未复权 {bad} 只")

    print()
    print("=" * 108)
    print("E. 腾讯 [72]/[73] 字段语义（疑似股本）")
    print("=" * 108)
    raw = df.http_get("https://qt.gtimg.cn/q=sh601398")
    vals = raw.split('="', 1)[1].rstrip('";\n').split("~")
    for i in (38, 44, 45, 72, 73, 76):
        if i < len(vals) and vals[i].strip():
            print(f"  [{i}] {vals[i]}")


if __name__ == "__main__":
    main()
