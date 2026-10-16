from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'stock_rank_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("['emotion','情绪强势'],['focus','任一强势'],['both','趋势与情绪同时强']", "['emotion',DATA.emotion_relay?'接力观察':'情绪强势'],['focus','任一观察'],['both','趋势与接力同时满足']")
s=s.replace("['情绪前排','情绪前排']", "...(DATA.emotion_relay?[['空间高标','空间高标'],['题材领先候选','题材领先候选'],['同身位竞争','同身位竞争'],['同题材接续候选','同题材接续候选']]:[['情绪前排','情绪前排']])")
s=s.replace("esc(DATA.stock_board_ranking.sorting)","esc(DATA.emotion_relay?'综合参考顺序保留原排名；接力列按角色、高度、在板和反馈独立排序，不使用价格活跃分代表龙头地位。':DATA.stock_board_ranking.sorting)")
p.write_text(s,encoding='utf-8')
p=ROOT/'emotion_ui.js';s=p.read_text(encoding='utf-8')
s=s.replace("erMetric('已完成最高连板',meta.highest_completed+'板'", "erMetric('前一完成日最高连板',meta.highest_previous+'板'")
s=s.replace("<h3>完成连板梯队</h3>","<h3>前一完成日连板梯队</h3>")
s=s.replace("m.highest_completed+' / '+m.highest_live+'板'", "m.highest_previous+' / '+m.highest_live+'板'")
s=s.replace("erMetric('已完成 / 当前在板'", "erMetric('前一完成日 / 当前在板'")
s += '''
// Expired quotes disappear from current relay observations even if the browser
// stays on the same snapshot across lunch, close, or a missed refresh.
var ER_OLD_FRESH=refreshPageFreshness,ER_FRESH_KEY=null;
refreshPageFreshness=function(){var result=ER_OLD_FRESH(),rows=(DATA.stocks||[]).concat(DATA.coverage_catalog||[]),key=rows.filter(function(r){return r.emotion_relay&&r.emotion_relay.eligible&&erFresh(r.emotion_relay);}).map(function(r){return r.code;}).join(',');if(key!==ER_FRESH_KEY){ER_FRESH_KEY=key;if(STATE.pane==='emotion')renderEmotion();if(STATE.pane==='boards')erRenderBoards();if(STATE.pane==='stocks')renderStocks();}return result;};
'''
p.write_text(s,encoding='utf-8')
