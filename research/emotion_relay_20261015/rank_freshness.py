from pathlib import Path
p=Path(__file__).resolve().parents[2]/'stock_rank_ui.js';s=p.read_text(encoding='utf-8')
needle="tags=fresh?labels.filter(function(t){return t!=='涨停收复';}).map(function(t){return msTag(t,ctx.name+' · 源行情 '+(item.source_at||'待核验'));}).join(''):msTag('快照已过期');"
replacement="tags=msRankStyleTags(r,item,ctx.name,fresh);"
assert needle in s;s=s.replace(needle,replacement)
s += '''
function msRankStyleTags(row,item,name,fresh){var labels=(item.style_labels||[]).filter(function(t){return t!=='涨停收复';});if(!DATA.emotion_relay)return fresh?labels.map(function(t){return msTag(t,name+' · 源行情 '+(item.source_at||'待核验'));}).join(''):msTag('快照已过期');var m=row.emotion_relay||{},mt=row.ma_trend||{},relay=['接力观察','暂无接力事件'].concat(m.roles||[]),tags=labels.filter(function(t){return relay.indexOf(t)>=0?erFresh(m):mtSnapshotFresh(mt);}).map(function(t){return msTag(t,name+' · 源行情 '+(relay.indexOf(t)>=0?m.quote_at:mt.quote_at||item.source_at||'待核验'));}).join('');return tags||(!erFresh(m)&&!mtSnapshotFresh(mt)?msTag('快照已过期'):'');}
'''
p.write_text(s,encoding='utf-8')
