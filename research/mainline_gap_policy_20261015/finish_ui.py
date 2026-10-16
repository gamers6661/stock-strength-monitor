from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'emotion_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace('共享确认题材','有共同主营行业或明确业务主线依据')
s=s.replace('同题材首板批次','共同主营行业或业务主线的首板批次')
s=s.replace("esc(n.board)+'</span>","msTag(n.board,(n.boards||[]).map(function(b){return b.basis||b.name;}).join('；'))+'</span>")
s=s.replace("+'日</span></p>'", "+'日 · '+esc((n.boards||[]).map(function(b){return b.name;}).join(' / '))+'</span></p>'")
s=s.replace("'停牌核心观察':'有日期有效的全天停牌公告证据，保留停牌前真实成交日与已完成高度，不计入当日在板或晋级分母。'",
    "'停牌核心观察':'保留停牌前真实成交日与已完成高度，不计入当日在板或晋级分母。公告核验与单股重试失败后的规则推定分别标注。',\n '停牌（按缺失规则推定）':'同批其他股票已取得当日成交，本股单独重试仍无当日成交。按用户指定规则作为停牌保留，属于规则推定，不代表已取得停牌公告。'")
p.write_text(s,encoding='utf-8')
p=ROOT/'radar_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("+(paused?'停牌中 · 保留停牌前历史K线；复牌后继续绘制。'", "+(paused?msChartAcquisitionNote(s)+'停牌中 · 保留停牌前历史K线；复牌后继续绘制。'")
s=s.replace("fmt(s.price,2)+' <small>'+pctHtml(s.change_pct,2)", "fmt(paused?((s.emotion_relay||{}).price||s.last_completed_close||s.price):s.price,2)+' <small>'+(paused?'停牌参考':pctHtml(s.change_pct,2))")
p.write_text(s,encoding='utf-8')
