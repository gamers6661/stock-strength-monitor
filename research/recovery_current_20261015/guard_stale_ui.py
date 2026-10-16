from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];p=ROOT/'ma_trend_ui.js';s=p.read_text(encoding='utf-8')
old="function mtStatus(m){var badge=msRecoveryTag(m),status=m.status||'未入选';"
new="function mtStatus(m){var badge=msRecoveryTag(m),status=m.candidate_mode&&!mtSnapshotFresh(m)?'快照已过期':m.status||'未入选';"
assert old in s;s=s.replace(old,new)
old="</span></div>';return '<b '+msTipAttrs(o.kind||'无强势起点')"
new="</span></div>';if(m.candidate_mode)return '<span class=\"ms-muted\">当前无有效候选</span>';return '<b '+msTipAttrs(o.kind||'无强势起点')"
assert old in s;s=s.replace(old,new)
old="if(msRecoveryCandidate(m))return mtRecoveryDetail(m);var p="
new="if(msRecoveryCandidate(m))return mtRecoveryDetail(m);if(m.candidate_mode)return '<details class=\"card ma-trend-detail\"><summary>候选核验状态 · '+esc(mtSnapshotFresh(m)?m.status:'快照已过期')+'</summary><p>当前无有效涨停收复候选标签。'+esc(m.reason||'等待最新报价及支撑核验')+'</p><p class=\"ms-muted\">源行情 '+esc(m.quote_at||'待更新')+'</p></details>';var p="
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
