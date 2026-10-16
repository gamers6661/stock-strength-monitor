from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def edit(name,pairs):
    p=ROOT/name;s=p.read_text(encoding='utf-8')
    for a,b in pairs:
        assert a in s,(name,a[:90]);s=s.replace(a,b)
    p.write_text(s,encoding='utf-8')
edit('emotion_ui.js',[
    ("fmt(s.seal_amount_yuan/10000,0)+'万", "unitYi(s.seal_amount_yuan,'元')+'"),
    ("fmt(s.amount_yuan/10000,0)+'万", "unitYi(s.amount_yuan,'元')+'"),
    ("esc(m.suspended_current?'停牌公告已核验':m.mode||'')", "esc(m.suspended_current?((m.suspension||{}).inferred?'停牌 · 按缺失规则推定':'停牌公告已核验'):m.mode||'')"),
])
edit('radar_ui.js',[
    ("items.length>=5", "items.length>=1"),("hasOHLC=bars.length>=5", "hasOHLC=bars.length>=1"),
    ("function msChartAcquisitionNote(s)", "function msHistoryGaps(s){var o=s.chart_observation||{},days=o.suspension_days||[];return days.length?'<details class=\"ms-history-gaps\"><summary>停牌标注（缺失规则推定） · '+days.length+'日</summary><p>'+days.map(esc).join(' / ')+'</p><p class=\"ms-muted\">缺失交易日按停牌处理，仅绘制有效成交日；无公告证据的日期属于规则推定。</p></details>':'';}\nfunction msChartAcquisitionNote(s)"),
    ("+'</p>')+'</section>'+msDetail", "+'</p>')+msHistoryGaps(s)+'</section>'+msDetail"),
    ("MS_CHART={bars:bars,price:price};", "var gaps=(s.chart_observation||{}).suspension_days||[];bars=bars.map(function(b,i){return Object.assign({},b,{suspension_before:gaps.filter(function(d){return i>0&&d>bars[i-1].date&&d<b.date;})});});MS_CHART={bars:bars,price:price};"),
    ("g.fillText('成交量',pad,volTop-3);", "g.fillText('成交量（亿股）',pad,volTop-3);g.fillText(unitYi(maxVol,'股'),pad,volTop+10);bars.forEach(function(b,i){if((b.suspension_before||[]).length){g.fillStyle='#687f9d';g.fillText('停',x(i)-4,top+9);}});"),
    ("+' · 成交量 '+fmt(b.volume,0)", "+' · 成交量 '+unitYi(b.volume,'股')+((b.suspension_before||[]).length?' · 前段停牌（推定） '+b.suspension_before.join(' / '):'')"),
])
edit('stock_rank_ui.js',[("'日线待更新':'最新完成交易日尚未被历史日线覆盖，暂停相关均线判断。'", "'日线待更新':'历史缺失交易日按停牌处理，使用实际取得的有效成交日继续判断；仅真实价格口径冲突暂停计算。'"),
    ("var MS_EXPLANATIONS={", "var MS_EXPLANATIONS={\n '有效样本观察':'展示全部真实日线，能形成完整周期的均线正常计算；尚未凑足周期的指标留空，不补造历史或价格。',\n '停牌观察':'同批其他股票有当日成交，本股单独重试后仍未获取到当日成交，按缺失规则推定停牌，保留最后有效阶段，复牌后继续。',")])
edit('csv_export.js',[("w.volume0,w.price_basis", "typeof w.volume0==='number'?w.volume0/1e8:null,w.price_basis")])
