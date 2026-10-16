from pathlib import Path

p=Path('dashboard_template.html')
s=p.read_text(encoding='utf-8')
start=s.index('/* ── 板块四象限：')
end=s.index('function renderFilterPanel(){',start)
s=s[:start]+s[end:]
s=s.replace("'相对强度':'rs','资金强度':'fund',", "'相对强度':'rs',")
s=s.replace('  // 之前没有资金分与60日位置的区间，用户想筛"资金流入前30%"只能靠状态标签猜。',
            '  // 数值区间与状态标签共同表达筛选条件。')
p.write_text(s,encoding='utf-8')
