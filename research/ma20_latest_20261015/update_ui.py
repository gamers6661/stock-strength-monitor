from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for name in ('radar_ui.js','stock_rank_ui.js','ma_trend_ui.js'):
    path=ROOT/name;text=path.read_text(encoding='utf-8').replace('pct(', 'pctHtml(')
    if name=='ma_trend_ui.js':
        text=text.replace("esc(m.stage_label||'暂无合格阶段')", "esc((mtHistorical(m)?'历史阶段 · ':'')+(m.stage_label||'暂无合格阶段'))")
        text=text.replace("<span class=\"cd\">'+esc(m.reason||'')", "<span class=\"cd ma-reason\" '+msTipAttrs(m.status,m.reason)+'>'+esc(m.reason||'')")
        text=text.replace("mtValue(o.day_return_pct)+'%'", "pctHtml(o.day_return_pct)")
        text=text.replace("mtValue(p.rise_pct)+'%", "pctHtml(p.rise_pct)+'")
        text=text.replace("mtValue(o.day_return_pct)+'% / 两日 '+mtValue(o.two_day_return_pct)+'%", "pctHtml(o.day_return_pct)+' / 两日 '+pctHtml(o.two_day_return_pct)+'")
        text=text.replace("mtValue(pl.rise_pct)+'% / '", "pctHtml(pl.rise_pct)+' / '")
        text=text.replace("<p>锁定平台 ", "<p>最近上涨 '+esc(pl.rise_start||pl.base_at||'—')+' → '+esc(pl.rise_end||pl.peak_date||'—')+'；整理起于 '+esc(pl.start||'—')+'；平台底部保留 '+pctHtml(pl.retained_pct)+' / '+mtValue(pl.retained_atr)+' ATR。振幅 '+pctHtml(pl.width_pct)+'（超过10%仅提示），宽度 '+mtValue(pl.width_atr)+' ATR（≤2）。</p><p>锁定平台 ")
        # The same settled range is shown next to the locked defense price.
        text=text.replace("<span class=\"cd\">暂态MA", "<span class=\"cd\">'+(m.stage===20&&p.start?'平台 '+esc(p.start)+' → '+esc(p.validated_at||p.formed_at||'—')+' · '+mtValue(p.low,3)+'—'+mtValue(p.high,3):'')+'</span><span class=\"cd\">暂态MA")
    path.write_text(text,encoding='utf-8')
print('UI display updated')
