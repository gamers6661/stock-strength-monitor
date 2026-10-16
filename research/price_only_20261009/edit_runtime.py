from pathlib import Path

def replace_range(text, start, end, replacement):
    a=text.index(start);b=text.index(end,a)
    return text[:a]+replacement+text[b:]

p=Path('scoring.py');s=p.read_text(encoding='utf-8')
s=s.replace('import fund_history\n','import price_only\n').replace('import fund_confirmation\n','')
s=s.replace("CLOSE_REFRESH_VERSION = '收盘优先发布1'", "CLOSE_REFRESH_VERSION = '收盘价格优先发布2'")
s=s.replace(' + 资金流','').replace('先发布榜单，再由服务后台补采辅助资金','正式日线就绪即发布榜单')
s=replace_range(s,'    # 2. 东财概念板块实时','    n_exact_f = n_exact_l = 0',
    '    # 资金排序已取消；保留同花顺价量和成员联动。\n    em_meta = {"source": "已停用", "stale": False, "coverage": 0}\n    tg_by_key = theme_groups or {}\n')
s=replace_range(s,'        # 真实资金缺失保持未知','        # ── 联动',
    '        fu, fund_src = None, "已停用"\n\n')
s=s.replace('        if fu is not None:\n            components.append((w["fund"], fu))\n','')
s=replace_range(s,'        # 口径置信度折扣','        boards.append({','')
s=s.replace('print(f"[BOARD] 同名核对：真实资金 {n_exact_f}/{n} ｜ 主板成员联动 {n_exact_l}/{n}")','print(f"[BOARD] 主板成员联动 {n_exact_l}/{n}")')
s=replace_range(s,'    # 4. 资金流：','    # 4·补、题材分组',
    '    # 不再获取或使用任何资金流入/流出数据。\n    fund_map = {}\n    fund_meta = {"source": "已停用", "enabled": False, "stale": False, "coverage": 0}\n    snap.update(fund_available=False, fund_source="已停用", fund_meta=fund_meta)\n\n')
s=replace_range(s,'        # 日线资格不依赖历史资金','    try:\n        stocks, model',
    '        snap["fund_history"] = {"enabled": False, "requested": 0}\n')
s=replace_range(s,'    snap["fund_confirmation"] = fund_confirmation.attach','    snap["strength_model"] = model',
    '    price_only.clear_rows(stocks)\n')
s=s.replace("    snap['fund_confirmation']=fund_confirmation.attach(stocks+catalog,strength.trading_calendar(completed_bars),fetch=False)","    price_only.sanitize(snap)")
p.write_text(s,encoding='utf-8')

p=Path('attack_model.py');s=p.read_text(encoding='utf-8')
s=replace_range(s,'def _legacy_fund_confirmation','def enrich','')
p.write_text(s,encoding='utf-8')

p=Path('report.py');s=p.read_text(encoding='utf-8')
s='\n'.join(line for line in s.split('\n') if not any(k in line for k in ('f"当日资金：','f"同源日级资金历史覆盖','"- 主力净额是','"- 日级资金使用')))
s=s.replace('只陈述完成日线与已取得的资金数据','只陈述完成日线、价格和成交量数据')
p.write_text(s,encoding='utf-8')
