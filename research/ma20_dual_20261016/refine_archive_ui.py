from pathlib import Path
p=Path(__file__).resolve().parents[2]/'ma_trend_ui.js'
s=p.read_text(encoding='utf8')
old="+'<p>阶段转换 '+esc((m.transitions||[]).map(function(t){return (t.at||t.date)+' MA'+t.from_stage+'→MA'+t.to_stage;}).join('；')||'暂无')+'</p><p>单日上涨 '"
assert s.count(old)==1
s=s.replace(old,"+'<p>单日上涨 '")
start=s.index("+'<p>'+esc(pl.confirmed?'锁定后备平台'")
tail="+'</p><p>本次底部反弹 '"
end=s.index(tail,start)
original=s[start+1:end]+"+'</p>'"
s=s[:start]+"+(m.stage===20&&!pl.start?'<p class=\"ms-muted\">后备平台尚未形成，当前以MA20防守。</p>':"+original+")+"+"'<p>本次底部反弹 '"+s[end+len(tail):]
p.write_text(s,encoding='utf8')
