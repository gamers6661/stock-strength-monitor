from pathlib import Path
p=Path(__file__).resolve().parents[2]/'ma_trend_ui.js'
s=p.read_text(encoding='utf-8')
changes=[
    ("o=m.origin||{},p=m.platform||{};if(c)","o=m.origin||{},p=m.ma20_entry||m.platform||{};if(c)"),
    ("pl=m.platform||{},rb=m.rebound||{};", "pl=m.platform||{},rise=m.ma20_entry||pl,rb=m.rebound||{};"),
    ("mtValue(m.ma_value,4)+'</p><p>'+(mtHistorical", "mtValue(m.ma_value,4)+'</p>'+mtDefense(m)+'<p>'+(mtHistorical"),
    ("pctHtml(pl.rise_pct)+' / '+mtValue(pl.rise_atr)+' ATR；固定低点 '+mtValue(pl.base_low)+'（'+esc(pl.base_at", "pctHtml(rise.rise_pct)+' / '+mtValue(rise.rise_atr)+' ATR；固定低点 '+mtValue(rise.base_low)+'（'+esc(rise.base_at"),
    ("esc(pl.confirmed?'锁定平台':'承接区间（平台尚未确认）')", "esc(pl.confirmed?'锁定后备平台':m.stage===20?'暂无合格后备平台，当前以MA20防守':'承接区间（平台尚未确认）')"),
]
for old,new in changes:
    assert s.count(old)==1,(old,s.count(old))
    s=s.replace(old,new)
p.write_text(s,encoding='utf-8')
