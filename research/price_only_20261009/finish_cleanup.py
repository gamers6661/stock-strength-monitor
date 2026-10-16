from pathlib import Path

p=Path('dashboard_template.html');s=p.read_text(encoding='utf-8')
for labels in ("'主力3日净额亿元','主力5日净额亿元','主力10日净额亿元','资金核验日',",
               ",'当日资金净额亿元','当日资金来源','当日资金采集时间'",
               "'资金分','资金实际权重%','资金占成交额%','资金判断状态',",
               "'资金历史完成日数','资金历史缺口原因',"):
    assert labels in s, labels
    s=s.replace(labels,'')
for values in (',s.fund3_yi,s.fund5_yi,s.fund10_yi,s.fund_asof',
               ',s.fund_today_yi,s.fund_today_source,s.fund_today_at',
               ',f.score,f.weight==null?null:f.weight*100,f.ratio,f.status',
               ',s.fund_history_days,s.fund_history_reason'):
    assert values in s, values
    s=s.replace(values,'')
s=s.replace("var v=n(t.main_net_sum);","var v=n(t.amount_wan);")
s=s.replace("['相对强度',fmt(b.rs,1),'']", "['相对强度',fmt(b.rs,1),'']")
s=s.replace("['价格进攻分','价格进攻档位','距盘中MA5_ATR']", "['价格进攻分','价格进攻档位','距盘中MA5_ATR']")
s=s.replace("+uiMetric('价格进攻',s.live_attack_price_score==null?null:fmt(s.live_attack_price_score,1),'分','5/10/20日实际推进与相对速度的价格进攻分。')", "+uiMetric('日线进攻',source.stock_strength_score==null?null:fmt(source.stock_strength_score,1),'分','完成日线进攻分，和盘中价格进攻分别判断。')")
s='\n'.join(line for line in s.split('\n') if not line.startswith('var FUND_TIP='))
p.write_text(s,encoding='utf-8')

p=Path('scoring.py');s=p.read_text(encoding='utf-8')
a=s.index('    # 主力资金仅保留真实来源的展示分位');b=s.index('    for s in stocks:\n        mapping =',a)
s=s[:a]+'    price_only.clear_rows(stocks)\n'+s[b:]
s=s.replace('    config.atomic_write_text(config.SNAPSHOT_JSON,\n                             json.dumps(snap,', '    price_only.sanitize(snap)\n    snap["close_refresh_version"] = CLOSE_REFRESH_VERSION\n    config.atomic_write_text(config.SNAPSHOT_JSON,\n                             json.dumps(snap,',1)
p.write_text(s,encoding='utf-8')
