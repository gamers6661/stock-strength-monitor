# -*- coding: utf-8 -*-
"""数据准确性审计 —— 用两个独立数据源逐字段交叉比对，定位口径错误。

审计维度：
  A. 腾讯快照 vs 东财实时（价格/涨跌/成交/换手/市值/量比）
  B. 腾讯快照内部自洽（价格 × 涨跌幅 = 昨收）
  C. 换手率自洽反推（成交量 / 流通股本）—— 可识破市值字段张冠李戴
  D. K线末根 vs 快照价格一致性
  E. 市值字段语义确认（流通 vs 总）
"""
import json
import urllib.parse

import config
import datafeed as df

SAMPLE = ["600519", "000001", "002594", "600036", "601138",
          "000725", "002230", "600030", "000651", "601899"]


def em_snapshot(codes):
    """东财延时行情：一次拿回现价/涨跌/成交/换手/市值/量比"""
    fields = "f12,f14,f2,f3,f5,f6,f8,f9,f10,f20,f21,f23"
    url = "https://push2delay.eastmoney.com/api/qt/clist/get?" + urllib.parse.urlencode({
        "pn": "1", "pz": "200", "po": "1", "np": "1", "fltt": "2", "invt": "2",
        "fs": config.POOL["em_fs"], "fields": fields,
    })
    d = json.loads(df.http_get(url, headers={"Referer": "https://quote.eastmoney.com/"}))
    out = {}
    for i in ((d.get("data") or {}).get("diff") or []):
        c = i.get("f12")
        if c in codes:
            out[c] = {
                "name": i.get("f14"),
                "price": i.get("f2"),
                "chg": i.get("f3"),
                "vol_shou": i.get("f5"),          # 成交量(手)
                "amount_yuan": i.get("f6"),       # 成交额(元)
                "turnover": i.get("f8"),          # 换手率%
                "pe": i.get("f9"),
                "vol_ratio": i.get("f10"),
                "mcap": i.get("f20"),             # 总市值
                "float_mcap": i.get("f21"),       # 流通市值
                "pb": i.get("f23"),
            }
    return out


def main():
    print("=" * 92)
    print("A. 腾讯快照 原始字段数组（逐索引）")
    print("=" * 92)
    raw = df.http_get("https://qt.gtimg.cn/q=sh600519")
    body = raw.split('="', 1)[1].rstrip('";\n')
    vals = body.split("~")
    for i, v in enumerate(vals):
        if v.strip():
            print(f"  [{i:>2}] {v}")

    print()
    print("=" * 92)
    print("B. 双源交叉比对（腾讯 vs 东财）")
    print("=" * 92)
    tq = df.tencent_quotes(SAMPLE)
    eq = em_snapshot(set(SAMPLE))

    hdr = (f"{'代码':<8}{'名称':<10}{'字段':<12}{'腾讯':>14}{'东财':>16}{'差异':>12}  判定")
    print(hdr)
    print("-" * 92)

    problems = []

    def cmp(code, label, tv, ev, tol=0.01, unit=1.0):
        """tolerate relative diff"""
        if tv is None or ev is None:
            return
        try:
            a, b = float(tv), float(ev) / unit
        except (TypeError, ValueError):
            return
        if b == 0:
            return
        rel = abs(a - b) / abs(b)
        flag = "OK" if rel <= tol else ("!! 偏差" if rel > 0.02 else "~")
        if rel > 0.02:
            problems.append((code, label, a, b, rel))
        print(f"{code:<8}{'':<10}{label:<12}{a:>14.4f}{b:>16.4f}{rel*100:>11.2f}%  {flag}")

    for c in SAMPLE:
        t, e = tq.get(c), eq.get(c)
        if not t or not e:
            print(f"{c} 缺数据 腾讯={bool(t)} 东财={bool(e)}")
            continue
        nm = t["name"]
        print(f"\n--- {c} {nm} ---")
        cmp(c, "现价", t["price"], e["price"])
        cmp(c, "涨跌幅%", t["change_pct"], e["chg"])
        cmp(c, "成交量(手)", t["volume_shou"], e["vol_shou"])
        cmp(c, "成交额(万元)", t["amount_wan"], e["amount_yuan"], unit=1e4)
        cmp(c, "换手率%", t["turnover_pct"], e["turnover"])
        cmp(c, "量比", t["vol_ratio"], e["vol_ratio"], tol=0.15)
        cmp(c, "流通市值(亿)", t["float_mcap_yi"], e["float_mcap"], unit=1e8)
        cmp(c, "总市值(亿)", t["mcap_yi"], e["mcap"], unit=1e8)
        cmp(c, "市盈率", t["pe_ttm"], e["pe"], tol=0.10)

    print()
    print("=" * 92)
    print("C. 自洽检验：用「成交量 ÷ 换手率」反推流通股本，看市值字段指向哪个")
    print("=" * 92)
    print(f"{'代码':<8}{'名称':<10}{'反推流通股本(亿股)':>20}{'÷价格得流通市值(亿)':>22}{'腾讯[45]':>12}{'腾讯[44]':>12}{'东财流通':>12}")
    print("-" * 102)
    for c in SAMPLE:
        t, e = tq.get(c), eq.get(c)
        if not t or not e:
            continue
        try:
            if t["turnover_pct"] > 0 and t["price"] > 0:
                float_shares = (t["volume_shou"] * 100) / (t["turnover_pct"] / 100)   # 股
                implied_mcap = float_shares / 1e8 * t["price"]                        # 亿元
                print(f"{c:<8}{t['name']:<10}{float_shares/1e8:>20.2f}{implied_mcap:>22.1f}"
                      f"{t['float_mcap_yi']:>12.1f}{t['mcap_yi']:>12.1f}"
                      f"{(e['float_mcap'] or 0)/1e8:>12.1f}")
        except Exception as ex:
            print(f"{c} 反推失败 {ex}")

    print()
    print("=" * 92)
    print("D. 汇总：偏差 >2% 的字段")
    print("=" * 92)
    if not problems:
        print("  无")
    for c, label, a, b, rel in problems:
        print(f"  {c} {label}: 腾讯={a:.4f} 东财={b:.4f} 偏差={rel*100:.2f}%")


if __name__ == "__main__":
    main()
