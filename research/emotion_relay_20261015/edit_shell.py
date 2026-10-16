from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];p=ROOT/'dashboard_template.html';s=p.read_text(encoding='utf-8')
start=s.find('<!-- ══════ 题材 ══════ -->');end=s.index('<!-- ══════ 持仓 ══════ -->',start) if start>=0 else -1
if start>=0:s=s[:start]+'''<!-- Emotion is independent from the MA radar. -->
<section class="pane" id="p-emotion">
  <div class="hero"><div class="er-eyebrow">沪深主板 · 龙头接力</div><h1>情绪接力</h1><p id="emotion-sub">收盘高度与盘中在板分别核验，观察梯队、分歧反馈和题材接续。</p></div>
  <div class="main" style="padding-top:0"><div id="emotion-host"></div></div>
</section>
<section class="pane" id="p-themes" hidden aria-hidden="true"><div id="theme-center"></div></section>

'''+s[end:]
if "if(p==='themes')p='boards';" not in s:s=s.replace("function goPane(p){\n", "function goPane(p){\n  if(p==='themes')p='boards';\n")
p.write_text(s,encoding='utf-8')
p=ROOT/'stock_rank_ui.js';s=p.read_text(encoding='utf-8')
old="ranking:b?b.stock_ranking:(DATA.stock_board_ranking||{}).all"
new="ranking:((DATA.emotion_relay||{}).rankings||{})[b?b.id:'all']||(b?b.stock_ranking:(DATA.stock_board_ranking||{}).all)"
assert old in s;s=s.replace(old,new)
old="function msRankFresh(row,item){var m=";new="function msRankFresh(row,item){if(DATA.emotion_relay&&row.emotion_relay)return erFresh(row.emotion_relay);var m="
assert old in s;s=s.replace(old,new)
s=s.replace("['emotion','情绪强度排序']", "['emotion',DATA.emotion_relay?'接力地位排序':'情绪强度排序']")
s=s.replace("<th>情绪强度 / 板块名次</th>", "<th>'+(DATA.emotion_relay?'接力地位 / 板块名次':'情绪强度 / 板块名次')+'</th>")
old="msBadge(m,'emotion')+'<span class=\"cd\">'+(item.emotion_rank==null?'待核验':'板块第 '+item.emotion_rank+' / '+ranking.emotion_valid)+'</span></td>"
new="(DATA.emotion_relay?erRankCell(r,item,ranking):msBadge(m,'emotion')+'<span class=\"cd\">'+(item.emotion_rank==null?'待核验':'板块第 '+item.emotion_rank+' / '+ranking.emotion_valid)+'</span>')+'</td>"
assert old in s;s=s.replace(old,new)
s=s.replace("情绪有效 '+((ctx.ranking||{}).emotion_valid||0)", "'+(DATA.emotion_relay?'接力候选':'情绪有效')+' '+((ctx.ranking||{}).emotion_valid||0)")
p.write_text(s,encoding='utf-8')
