"""逐股读取当天全部采集记录，保留缺口；判断只使用本轮以前的事实。"""
from datetime import datetime
import gzip
import json
import math
from pathlib import Path
import config

_CACHE = {}

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def observed(r):
    return len(r) > 31 and r[31] is True or len(r) > 12 and r[12] is True

def effective(r):
    return r[30] if len(r) > 30 and r[30] else r[1] if len(r) > 1 else None

def point(r, scan_at):
    def at(i): return r[i] if len(r) > i else None
    def boundary(period, column, appended):
        if at(28) is not True: return None
        if number(at(appended)): return at(appended)
        # 旧记录保存的是该次价格参与的暂态均线，从同一时点反算守线边界。
        return (period*at(column)-at(2))/(period-1) if number(at(column)) and number(at(2)) else None
    funded = isinstance(at(37), dict) and at(37).get('weight', 0) > 0
    return dict(at=effective(r), source_at=at(1), acquired_at=scan_at,
                valid=observed(r), price=at(2), change=at(3), score=at(4), trend=at(5),
                risk=at(6), state=at(22), event=at(23), flags=at(27) or [],
                relative=at(24), open_return=at(25), trend_ok=at(10),
                ma10=at(29) if at(28) is True else None,
                ma5=at(7) if at(28) is True else None,
                ma5_boundary=boundary(5,7,39), ma20=boundary(20,9,40),
                atr20=at(38) if at(28) is True else None,
                attack_score=None if funded else at(33), attack_tier=None if funded else at(34), attack_stage=at(35),
                attack=at(36) is True and not funded, fund=None)

def load(directory, day):
    import intraday
    path = Path(directory) / (day + '.jsonl')
    key = str(path.resolve())
    try: stat = path.stat()
    except OSError: return {'points': {}, 'latest_rows': {}}
    cached = _CACHE.get(key)
    if cached and cached.get('file_size', cached['size']) == stat.st_size and cached['mtime'] == stat.st_mtime_ns:
        return cached
    if cached and cached['size'] < stat.st_size:
        result, offset = cached, cached['size']
    else:
        result, offset = {'points': {}, 'latest_rows': {}}, 0
    with path.open('rb') as stream:
        stream.seek(offset)
        # 固定本次文件边界；半行留待下一轮补齐，不能把读取位置推进到半行中间。
        for line in stream.read(stat.st_size-offset).splitlines(keepends=True):
            if not line.endswith(b'\n'):
                break
            offset += len(line)
            try: record = json.loads(line)
            except ValueError: continue
            if record.get('day') != day: continue
            result['last_scan_at'] = record.get('scan_at')
            if any(observed(r) for r in record.get('rows', []) if isinstance(r, list)):
                result['last_valid_record'] = record
            for r in record.get('rows', []):
                if not isinstance(r, list) or len(r) < 13: continue
                p = point(r, record.get('scan_at'))
                if record.get('rule_version') != config.INTRADAY_RULE_VERSION:
                    p.update(score=None, attack_score=None, attack_tier=None, attack=False,
                             state='旧规则报价参考，进攻资格不复用')
                if record.get('price_basis_version') != intraday.PRICE_BASIS_VERSION:
                    p.update(ma10=None,ma5=None,ma5_boundary=None,ma20=None,atr20=None,
                             score=None,attack_score=None,attack_tier=None,attack=False,
                             state='旧价格口径报价参考，均线及进攻资格待核验')
                old = result['latest_rows'].get(r[0])
                if old and p['at'] and effective(old) and p['at'] < effective(old):
                    p.update(valid=False, state='迟到报价，不覆盖较新判断')
                result['points'].setdefault(r[0], []).append(p)
                if p['valid'] and record.get('price_basis_version') == intraday.PRICE_BASIS_VERSION:
                    result['latest_rows'][r[0]] = r
    result.update(size=offset, file_size=stat.st_size, mtime=stat.st_mtime_ns)
    _CACHE[key] = result
    return result

def save_acquisition(directory, quotes, captured_at, session, boundary=None):
    """全池原始输入另留压缩记录，扫描后续失败也不会丢失已获取的行情。"""
    keys = ('price','open','high','low','last_close','change_pct','amount_wan','volume_shou',
            'quote_at','price_basis','price_basis_source','last_close_semantics',
            'last_close_precision_digits','limit_up','limit_down','limit_pct','board_type','ts','data_availability')
    folder = Path(directory) / 'acquisitions'
    folder.mkdir(parents=True, exist_ok=True)
    day = captured_at.strftime('%Y-%m-%d')
    record = {'captured_at': captured_at.isoformat(sep=' ', timespec='seconds'),
              'session': session, 'boundary': boundary, 'fields': ['code']+list(keys),
              'rows': [[c]+[q.get(k) for k in keys] for c,q in sorted(quotes.items())]}
    with gzip.open(folder/(day+'.jsonl.gz'), 'at', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(',',':'))+'\n')

def gap_seconds(a, b):
    try:
        before, after = datetime.fromisoformat(a), datetime.fromisoformat(b)
    except (ValueError, TypeError): return None
    if before.date() != after.date(): return None
    seconds = (after-before).total_seconds()
    # 午休不是交易时间；13:00可与11:30收市判断相接。
    start, end = before.replace(hour=11,minute=30,second=0), before.replace(hour=13,minute=0,second=0)
    if after > start and before < end:
        seconds -= max(0, (min(after,end)-max(before,start)).total_seconds())
    return seconds

def attach(snap, history):
    """完整日内路径用于持续/回落和守线判断；页面只展开最近12次，磁盘保留全部。"""
    for row in (snap.get('stocks') or []) + (snap.get('coverage_catalog') or []):
        prior = history.get('points', {}).get(str(row['code']), [])
        valid = row.get('intraday_observation_available') is True
        current = dict(at=row.get('intraday_judgment_at'), source_at=row.get('intraday_quote_at'),
            acquired_at=snap.get('quote_capture_at'), valid=valid, price=row.get('price'), change=row.get('change_pct'),
            score=row.get('intraday_score'), trend=row.get('intraday_trend_state'),
            risk=row.get('intraday_risk_level'), state=row.get('intraday_observation_state'),
            event=row.get('intraday_transition'), flags=row.get('intraday_risk_flags') or [],
            ma10=row.get('intraday_ma10_trigger_price') if row.get('intraday_price_basis_comparable') is True else None,
            attack_score=row.get('live_attack_score'), attack_tier=row.get('live_attack_tier'),
            attack_stage=row.get('live_attack_stage'), attack=row.get('attack_observation_candidate') is True,
            fund=row.get('live_attack_fund'))
        points = prior + [current]
        observed_points = [p for p in points if p['valid'] and number(p['price'])]
        last = observed_points[-1] if observed_points else None
        row['intraday_last_judgment'] = dict(last) if last else None
        distinct, consecutive = [], []
        for p in points:
            if not p['valid']:
                consecutive = []
                continue
            if distinct and p['at'] == distinct[-1]['at']:
                # 同一行情时间重复获取可重评，但不会增加持续确认次数或重复事件。
                distinct[-1] = p
                if consecutive: consecutive[-1] = p
                continue
            gap = gap_seconds(distinct[-1]['at'],p['at']) if distinct else None
            if gap is None or not 0 <= gap <= 900: consecutive = []
            distinct.append(p); consecutive.append(p)
        hold_count, attack_count = 0, 0
        for p in reversed(consecutive):
            if p['attack']: attack_count += 1
            else: break
        for p in reversed(consecutive):
            if number(p['ma10']) and number(p['price']) and p['price'] >= p['ma10']: hold_count += 1
            else: break
        events = []
        for a,b in zip(distinct,distinct[1:]):
            gap = gap_seconds(a['at'],b['at'])
            if gap is None or not 0 <= gap <= 900 or b['at'] <= a['at'] or not all(number(p['ma10']) for p in (a,b)): continue
            if (a['price'] >= a['ma10']) != (b['price'] >= b['ma10']):
                events.append({'at':b['at'],'kind':'扫描观察到收复MA10' if b['price'] >= b['ma10'] else '扫描观察到失守MA10'})
        if not valid:
            state = '本轮待核验；保留最近有效判断' if last else '尚无有效判断'
        elif row.get('intraday_serious_weakness') is True:
            state = row.get('intraday_observation_state') or '风险观察'
        elif number(current['ma10']) and current['price'] >= current['ma10'] and events and events[-1]['kind']=='扫描观察到收复MA10':
            state = '扫描失守后收复 · 守线'+str(hold_count)+'次'
        elif attack_count >= 2:
            state = '进攻持续 · 连续'+str(attack_count)+'次有效采样'
        elif current['attack']:
            state = '进攻观察 · 本轮达标'
        elif len(distinct)>=2 and distinct[-2]['attack']:
            state = '进攻回落 · 前次进攻仍留档'
        else:
            state = row.get('intraday_observation_state') or row.get('intraday_trend_state') or '待核验'
        prices = [p['price'] for p in observed_points]
        scores = [p['score'] for p in distinct if number(p['score'])]
        row['intraday_path'] = dict(state=state, acquired_count=len(points), valid_count=len(observed_points),
            distinct_count=len(distinct), missing_count=sum(not p['valid'] for p in points),
            attack_consecutive=attack_count, ma10_hold_consecutive=hold_count,
            first_at=distinct[0]['at'] if distinct else None, last_at=last['at'] if last else None,
            score_change_from_first=round(scores[-1]-scores[0],2) if len(scores)>1 else None,
            observed_peak_price=max(prices) if prices else None,
            events=events, recent=points[-12:], note='采样间的路径不作推断；重复行情不增加持续次数，缺口打断连续确认')
    return snap
