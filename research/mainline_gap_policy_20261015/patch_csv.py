from pathlib import Path
p=Path(__file__).resolve().parents[2]/'csv_export.js';s=p.read_text(encoding='utf-8')
a="'今日涨幅%','真实涨停价','换手%'";b="'今日涨幅%','真实涨停价','换手%','成交额(亿元)','成交量(亿股)','封单金额(亿元)'"
assert a in s;s=s.replace(a,b)
a='m.feedback_pct,m.limit_price,m.turnover_pct,m.quote_at';b="m.feedback_pct,m.limit_price,m.turnover_pct,typeof m.amount_wan==='number'?m.amount_wan/1e4:null,m.volume_yi,typeof (m.cap_strength||{}).seal_amount_yuan==='number'?m.cap_strength.seal_amount_yuan/1e8:null,m.quote_at"
assert a in s;s=s.replace(a,b);p.write_text(s,encoding='utf-8')
