from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'ma_trend_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("m.minute_coverage.bars+'条</span>'", "m.minute_coverage.bars+'条'+(m.minute_coverage.no_trade_minutes?' · 无成交核验 '+m.minute_coverage.no_trade_minutes+'分钟':'')+'</span>'")
s=s.replace("m.minute_coverage.bars+' 条；对应报价 '", "m.minute_coverage.bars+' 条'+(m.minute_coverage.no_trade_minutes?'；累计成交量与成交额均未变化，已核验无成交 '+m.minute_coverage.no_trade_minutes+' 分钟':'')+'；对应报价 '")
p.write_text(s,encoding='utf-8')
p=ROOT/'stock_rank_ui.js';s=p.read_text(encoding='utf-8').replace("tags=fresh?labels.map(function(t)","tags=fresh?labels.filter(function(t){return t!=='涨停收复';}).map(function(t)")
p.write_text(s,encoding='utf-8')
