from pathlib import Path
root=Path(r'D:\股票强势监测')
def edit(name,a,b):
 p=root/name;s=p.read_text(encoding='utf-8');assert s.count(a)==1,(name,s.count(a),a[:60]);p.write_text(s.replace(a,b),encoding='utf-8');print('EDIT',name)
edit('stock_activity_rules.py',"VERSION = '个股主动强度V2.1-20261019.3'","VERSION = '个股主动强度V2.1-20261020.4'")
edit('stock_activity_engine.py',"""    elif (previous.get('version')=='个股主动强度V2.1-20261019.2'
          and previous.get('score_version')==SCORE_VERSION):
""","""    elif (previous.get('version') in ('个股主动强度V2.1-20261019.2',
                                       '个股主动强度V2.1-20261019.3')
          and previous.get('score_version')==SCORE_VERSION):
""")
# Extend page hints without changing existing user-selected filters.
edit('stock_activity_ui.js',"""' · 待核验 '+c.pending+'。板块筛选保留全池原始分数与榜内名次。'""","""' · 待核验 '+c.pending+'。若当前在日线参考页，实时启动已出现时请切换到“主动启动榜”；板块筛选保留全池原始分数与榜内名次。'""")
# Keep important source metadata in a named audit field.
edit('stock_activity.py',"""    if fallback:result['stock_activity_quote_mode']='收盘采样参考'
""","""    if fallback:result['stock_activity_quote_mode']='收盘采样参考'
    elif at<=original:
        result['stock_activity_quote_mode']='逐股校验独立采样'
""")
print('SECOND_PATCH_OK')
