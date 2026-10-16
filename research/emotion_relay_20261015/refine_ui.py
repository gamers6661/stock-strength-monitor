from pathlib import Path
p=Path(__file__).resolve().parents[2]/'emotion_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("c=meta.coverage||{},formal=meta.mode==='正式收盘';", "c=meta.coverage||{},cf=meta.yesterday_chain_feedback||{},formal=meta.mode==='正式收盘',live=erLive();")
s=s.replace("'<h2>'+esc(meta.state)","'<h2>'+esc(meta.state)") # The status below also records stale snapshots.
s=s.replace("esc(meta.state)+'</h2>'", "esc((live?'':'行情待更新 · 上次')+meta.state)+'</h2>'")
s=s.replace("formal?'当日收盘最高':'当前在板最高'", "formal?'当日收盘最高':live?'当前在板最高':'上次在板最高（待更新）'")
s=s.replace("h+='<section class=\"card\"><div class=\"er-section-heading\"><h3>分板位晋级与断板反馈", "h+='<section class=\"card\"><div class=\"er-section-heading\"><h3>分板位晋级与断板反馈")
s=s.replace("昨日断板队列 '+bf.expected", "昨日连板股（≥2板） '+cf.expected+'只，当前有效 '+cf.valid+'只 · 晋级 '+fmt(cf.promotion_pct,1)+'% · 反馈中位 '+pctHtml(cf.median_return_pct,2)+'。</p><p class=\"ms-muted\">昨日断板队列 '+bf.expected")
s=s.replace("erMetric('接力环境',esc(m.state)", "erMetric('接力环境',esc((erLive()?'':'待更新 · 上次')+m.state)")
s=s.replace("确认主板成员 · 当前 '+rows.length+'个方向。", "确认主板成员 · 当前 '+rows.length+'个方向 · 源行情 '+esc((erModel()||{}).source_at||'待更新')+(erLive()?'':' · 以下为上次行情参考')+'。")
p.write_text(s,encoding='utf-8')
