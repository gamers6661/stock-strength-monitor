"""冻结输入与规则后的描述性排序对照；不搜索参数，不改线上评分。"""
import csv
import gzip
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median

import config
import replay_strength
from research.rules_20260929 import frozen_stock_strength_v5 as stock_strength
import strength

OUT = Path(__file__).parent
TOP_N = 20
HORIZONS = (5, 10)
COST_PCT = 0.30
VARIANTS = ['20日涨幅', '四项强度'] + ['去掉' + stock_strength.LABELS[k] for k in stock_strength.WEIGHTS]


def valid_bar(bar):
    return bool(bar and strength.valid_bars([bar]))


def outcome(by_date, calendar, t, horizon):
    """日线只能排除明显成交障碍，不能证明真实成交或盘中成交路径。"""
    signal = by_date[calendar[t]]
    entry = by_date.get(calendar[t+1])
    if not valid_bar(entry):
        return {'status': 'entry_missing_or_no_trade'}
    if entry['open'] / signal['close'] - 1 >= .095:
        return {'status': 'entry_near_limit_up'}
    price = entry['open']
    peak, max_dd, adverse, previous = price, 0.0, 0.0, signal['close']
    gaps = 0
    for i in range(t+1, len(calendar)):
        bar = by_date.get(calendar[i])
        if not valid_bar(bar):
            gaps += 1
            continue
        adverse = min(adverse, (bar['low'] / price - 1) * 100)
        peak = max(peak, bar['close'])
        max_dd = min(max_dd, (bar['close'] / peak - 1) * 100)
        locked = bar['high'] == bar['low'] and bar['close'] / previous - 1 <= -.095
        previous = bar['close']
        if i >= t+horizon and not locked:
            return {'status': 'closed', 'entry_date': calendar[t+1], 'exit_date': calendar[i],
                    'net_pct': (bar['close']/price-1)*100-COST_PCT,
                    'close_drawdown_pct': max_dd, 'mae_pct': adverse,
                    'exit_delay': i-(t+horizon), 'path_missing_sessions': gaps,
                    'entry_amount_est_wan': config.bar_amount_wan(entry)}
    return {'status': 'unresolved_exit', 'entry_date': calendar[t+1], 'path_missing_sessions': gaps}


def rankings(codes, metrics, own):
    result = {
        '20日涨幅': sorted(codes, key=lambda c: (-metrics[c]['ret20'], c))[:TOP_N],
        '四项强度': sorted(codes, key=lambda c: (-own[c]['stock_strength_score'], c))[:TOP_N],
    }
    for removed, removed_weight in stock_strength.WEIGHTS.items():
        def subtotal(code):
            parts = own[code]['stock_strength_parts']
            return sum(parts[k]*w for k, w in stock_strength.WEIGHTS.items() if k != removed)/(1-removed_weight)
        result['去掉'+stock_strength.LABELS[removed]] = sorted(codes, key=lambda c: (-subtotal(c), c))[:TOP_N]
    return result


def avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    protocol_path = OUT/'rules.json'
    inputs_path = OUT/'inputs.json.gz'
    sources = ('strength.py', 'stock_strength.py', 'config.py', 'research/rules_20260929/compare.py')
    if protocol_path.exists():
        protocol = json.loads(protocol_path.read_text(encoding='utf8'))
        for name in sources:
            if (config.ROOT/name).read_bytes() != (OUT/'frozen_source'/Path(name).name).read_bytes():
                raise RuntimeError('规则或研究方法已变化，请使用新的研究目录；不覆盖本次冻结结果：'+name)
        with gzip.open(inputs_path, 'rt', encoding='utf8') as f:
            return protocol, json.load(f)
    pool, series = replay_strength.local_data()
    calendar = strength.trading_calendar(series)
    protocol = {
        'frozen_at': datetime.now().isoformat(timespec='seconds'),
        'daily_model': strength.VERSION, 'strength_model': stock_strength.VERSION,
        'intraday_rule': config.INTRADAY_RULE_VERSION,
        'data_start': calendar[0], 'data_end': calendar[-1], 'pool_size': len(pool),
        'core_bars': strength.CORE_BARS, 'weights': stock_strength.WEIGHTS,
        'persistent_criterion': stock_strength.PERSISTENT_CRITERION,
        'top_n': TOP_N, 'horizons': HORIZONS, 'assumed_cost_pct': COST_PCT,
        'groups': ['共同趋势池', '持续强势池'], 'variants': VARIANTS,
        'entry': '信号日之后首个市场交易日开盘；缺失/无成交/开盘涨幅>=9.5%跳过，不补选',
        'exit': '第5/10市场交易日收盘；缺失/无成交/一字跌停顺延至首次可观察退出，末端未退出单列',
        'comparison': '同一日同一候选池；删项后剩余权重按原比例归一；不改入选池、不做参数搜索',
        'gaps': '核心窗口日期及OHLCV完整才计分；未来缺失不改变原排名，逐事件披露',
        'liquidity': '记录信号日前20日估算成交额中位数；无历史成交额淘汰线',
    }
    frozen = OUT/'frozen_source'
    frozen.mkdir(exist_ok=True)
    for name in sources:
        (frozen/Path(name).name).write_bytes((config.ROOT/name).read_bytes())
    data = {'pool': pool, 'series': series, 'calendar': calendar}
    with gzip.open(inputs_path, 'wt', encoding='utf8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf8')
    return protocol, data


def run():
    protocol, data = freeze()
    series, calendar = data['series'], data['calendar']
    indexes = {c: {b['date']: i for i,b in enumerate(bs)} for c,bs in series.items()}
    by_date = {c: {b['date']: b for b in bs} for c,bs in series.items()}
    cohorts, events, selections = [], [], []
    prior_lists = {}
    excluded = Counter()
    for t in range(strength.CORE_BARS-1, len(calendar)-max(HORIZONS)):
        day = calendar[t]
        wanted = calendar[t-strength.CORE_BARS+1:t+1]
        metrics, windows = {}, {}
        for c, bs in series.items():
            end = indexes[c].get(day)
            if end is None or end < strength.CORE_BARS-1:
                excluded['missing_or_short'] += 1
                continue
            window = bs[end-strength.CORE_BARS+1:end+1]
            issue = strength.core_window_issue(window, wanted)
            if issue:
                excluded[issue] += 1
                continue
            metrics[c] = strength.day_metrics(window)
            windows[c] = window
        own, _ = stock_strength.score(metrics, {c:{} for c in metrics}, windows)
        groups = {'共同趋势池': [c for c in metrics if metrics[c]['trend_online']],
                  '持续强势池': [c for c in own if own[c]['persistent_strong']]}
        forward = {}
        for group, candidates in groups.items():
            if len(candidates) < TOP_N:
                excluded[group+'_less_than20'] += 1
                continue
            ranks = rankings(candidates, metrics, own)
            for variant, codes in ranks.items():
                last = prior_lists.get((group,variant))
                retention = len(set(codes)&set(last))/TOP_N*100 if last is not None else None
                prior_lists[group,variant] = codes
                selection = {'date':day,'group':group,'variant':variant,'candidate_count':len(candidates),
                             'codes': codes, 'retention_pct':retention,
                             'overlap_baseline_pct':len(set(codes)&set(ranks['20日涨幅']))/TOP_N*100,
                             'signal_amount_median_wan':median(metrics[c]['amt_med20_wan'] for c in codes)}
                selections.append(selection)
                for horizon in HORIZONS:
                    outcomes = []
                    for code in codes:
                        key = code,horizon
                        if key not in forward:
                            forward[key] = outcome(by_date[code],calendar,t,horizon)
                        result = forward[key]
                        outcomes.append(result)
                        events.append(dict(date=day,group=group,variant=variant,horizon=horizon,
                                           code=code,signal_amount_med20_wan=metrics[code]['amt_med20_wan'],**result))
                    closed = [r for r in outcomes if r['status']=='closed']
                    unknown = any(r['status']=='unresolved_exit' for r in outcomes)
                    cohorts.append({'date':day,'signal_index':t,'group':group,'variant':variant,
                                    'horizon':horizon,'selected':TOP_N,'closed':len(closed),
                                    'status_counts':dict(Counter(r['status'] for r in outcomes)),
                                    'closed_mean_net_pct':avg([r['net_pct'] for r in closed]),
                                    'fixed_slots_net_pct':None if unknown else sum(r['net_pct'] for r in closed)/TOP_N,
                                    'close_drawdown_pct':avg([r['close_drawdown_pct'] for r in closed]),
                                    'mae_pct':avg([r['mae_pct'] for r in closed]),
                                    'delayed_exits':sum(r['exit_delay']>0 for r in closed),
                                    'path_gaps':sum(r.get('path_missing_sessions',0)>0 for r in outcomes)})
        if (t-strength.CORE_BARS+1)%15==0:
            print('进度',day,'有效样本',len(metrics),flush=True)
    summaries=[]
    for group in protocol['groups']:
        for horizon in HORIZONS:
            for variant in VARIANTS:
                rows=[r for r in cohorts if r['group']==group and r['horizon']==horizon and r['variant']==variant]
                same=[s for s in selections if s['group']==group and s['variant']==variant]
                baseline={r['date']:r for r in cohorts if r['group']==group and r['horizon']==horizon and r['variant']=='20日涨幅'}
                paired=[(r['date'],r['fixed_slots_net_pct']-baseline[r['date']]['fixed_slots_net_pct'])
                        for r in rows if r['fixed_slots_net_pct'] is not None and baseline[r['date']]['fixed_slots_net_pct'] is not None]
                mid=len(paired)//2
                statuses=Counter()
                for r in rows: statuses.update(r['status_counts'])
                spaced=[r for r in rows if (r['signal_index']-(strength.CORE_BARS-1))%horizon==0]
                summaries.append({'group':group,'horizon':horizon,'variant':variant,'signal_days':len(rows),
                                  'closed_mean_net_pct':avg([r['closed_mean_net_pct'] for r in rows]),
                                  'fixed_slots_mean_net_pct':avg([r['fixed_slots_net_pct'] for r in rows]),
                                  'paired_days':len(paired),'paired_diff_pct':avg([v for _,v in paired]),
                                  'first_half_diff_pct':avg([v for _,v in paired[:mid]]),
                                  'second_half_diff_pct':avg([v for _,v in paired[mid:]]),
                                  'spaced_signal_days':len(spaced),
                                  'spaced_mean_net_pct':avg([r['fixed_slots_net_pct'] for r in spaced]),
                                  'close_drawdown_pct':avg([r['close_drawdown_pct'] for r in rows]),
                                  'mae_pct':avg([r['mae_pct'] for r in rows]),
                                  'retention_pct':avg([r['retention_pct'] for r in same]),
                                  'overlap_baseline_pct':avg([r['overlap_baseline_pct'] for r in same]),
                                  'signal_amount_median_wan':avg([r['signal_amount_median_wan'] for r in same]),
                                  'statuses':dict(statuses),'delayed_exits':sum(r['delayed_exits'] for r in rows),
                                  'path_gaps':sum(r['path_gaps'] for r in rows)})
    result={'protocol':protocol,'excluded_stock_days':dict(excluded),'summaries':summaries,
            'cohorts':cohorts,'selections':selections}
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    fields=sorted(set().union(*(r.keys() for r in events)))
    with (OUT/'events.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(events)
    write_report(result)
    print('完成',OUT/'排序对照报告.md',flush=True)


def write_report(result):
    p=result['protocol']; summaries=result['summaries']
    def fmt(value): return '—' if value is None else f'{value:+.2f}%'
    lines=['# 冻结规则后的排序对照','',
           f"冻结时间：{p['frozen_at']}。本机数据：{p['data_start']} 至 {p['data_end']}；当前池 {p['pool_size']} 只。",'',
           f"日线模型 {p['daily_model']}，强度模型 {p['strength_model']}。核心窗口25日，权重保持35/25/20/20。",'',
           '每个完成日分别在共同趋势池、持续强势池选前20名。所有版本共用当日候选池；删项仅改变排序，剩余权重按原比例归一。持续强势池本身含四因子门槛，因此共同趋势池是主要比较，持续强势池作为现行筛选后的补充。', '',
           '次日开盘观察入场，固定5/10个市场交易日退出，假设往返成本0.30%。开盘近涨停、缺失或无成交不补选。到期一字跌停或无有效日线顺延；没有后续有效退出价的事件保留未结。', '',
           '固定名额均值：每个信号日20个等额名额，未入场名额按现金0收益处理；含未结退出的整批不进入该均值。与20日涨幅的差值只比较双方都有结果的同日批次。它是事件批次比较，不是资金组合收益。', '']
    for group in p['groups']:
        lines += ['## '+group,'']
        for horizon in HORIZONS:
            lines += [f'### {horizon}日观察','',
                      '| 排序 | 判断日 | 固定名额净均值 | 对涨幅差值 | 前半/后半差值 | 收盘路径回撤 | 最大不利波动 |',
                      '|---|---:|---:|---:|---:|---:|---:|']
            rows=[r for r in summaries if r['group']==group and r['horizon']==horizon]
            for r in rows:
                lines.append(f"| {r['variant']} | {r['signal_days']} | {fmt(r['fixed_slots_mean_net_pct'])} | {fmt(r['paired_diff_pct'])} | {fmt(r['first_half_diff_pct'])} / {fmt(r['second_half_diff_pct'])} | {fmt(r['close_drawdown_pct'])} | {fmt(r['mae_pct'])} |")
            lines += ['', '| 排序 | 间隔抽样批数/均值 | 完成/入场缺失/开盘近涨停/未结 | 延期退出 | 路径有缺口 |', '|---|---:|---:|---:|---:|']
            for r in rows:
                st=r['statuses']; counts='/'.join(str(st.get(k,0)) for k in ('closed','entry_missing_or_no_trade','entry_near_limit_up','unresolved_exit'))
                lines.append(f"| {r['variant']} | {r['spaced_signal_days']} / {fmt(r['spaced_mean_net_pct'])} | {counts} | {r['delayed_exits']} | {r['path_gaps']} |")
            lines += ['']
        lines += ['| 排序 | 相邻名单保留率 | 与涨幅名单重合 | 信号前20日估算成交额中位数的日均值 |','|---|---:|---:|---:|']
        for r in summaries:
            if r['group']==group and r['horizon']==5:
                amount=r['signal_amount_median_wan']
                lines.append(f"| {r['variant']} | {fmt(r['retention_pct'])} | {fmt(r['overlap_baseline_pct'])} | {amount:.0f} 万元 |" if amount is not None else f"| {r['variant']} | — | — | — |")
        lines += ['']
    lines += ['## 结论与使用范围','',
              '这次对照不自动改变权重；保留简单涨幅作为基准。要判断增量，需要同时看全段、前后半段、间隔抽样、回撤与名单稳定性，不能按本段均值挑出所谓最优版本。',
              '当前股票池回看有幸存者偏差，历史ST身份和历史成分不可完整还原；前复权日线及成交额估算不能证明真实可成交、容量或滑点。近涨停9.5%是普通主板的保守近似，不能精确覆盖历史全部制度状态。',
              '每日事件高度重叠，间隔5/10日抽样仍可能因延期退出而重叠；正收益、平均值均为描述结果，不推算独立样本显著性。收盘路径回撤不包含无法确定时序的日内高低点，最大不利波动另列，均不是组合最大回撤。',
              '未来缺口、跳过和未结事件逐笔保存在events.csv，不根据未来成交条件重新挑选股票。未结会使可比批次变少，结果须与未结数量一起阅读。',
              '这项研究只验证完成日线排序，不能验证盘中启动、15分钟回收、资金或题材助攻。新规则真实盘中记录继续按版本隔离积累。', '',
              '复现：在项目目录运行 `python -B -X utf8 -m research.rules_20260929.compare`。输入、规则及本次算法源码已冻结；源码变化会拒绝覆盖本次结果。', '']
    (OUT/'排序对照报告.md').write_text('\n'.join(lines),encoding='utf8')


if __name__=='__main__':
    run()
