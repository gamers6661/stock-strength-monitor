"""只核验已有概念指数日线，不修改筛选或运行数据。"""
import concurrent.futures
import json
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import datafeed

snapshot = json.loads((ROOT / 'cache/snapshot.json').read_text(encoding='utf-8'))
asof = snapshot['strength_model']['asof']
names = {'锂电池概念', 'PCB概念', '航运概念'}
codes = [(b['idx_code'], b['name']) for b in snapshot['boards'] if b['name'] in names]

def probe(item):
    name, bars = datafeed.fetch_ths_board_kline(item[0])
    usable = [bar for bar in bars if bar['date'] <= asof]
    closes = [bar['close'] for bar in usable]
    average = lambda n: sum(closes[-n:]) / n
    atr20 = sum(max(usable[i]['high'] - usable[i]['low'],
                    abs(usable[i]['high'] - usable[i - 1]['close']),
                    abs(usable[i]['low'] - usable[i - 1]['close']))
                for i in range(len(usable) - 20, len(usable))) / 20
    ma5, ma10, ma20 = average(5), average(10), average(20)
    ma20_prev = sum(closes[-21:-1]) / 20
    return dict(requested_name=item[1], returned_name=name, code=item[0], bars=len(usable),
                asof=usable[-1]['date'], ma5=round(ma5, 3), ma10=round(ma10, 3),
                ma20=round(ma20, 3), atr20=round(atr20, 3),
                trend_online=ma5 > ma10 > ma20 > ma20_prev and closes[-1] >= ma10,
                last_bar=usable[-1])

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(probe, codes))
print(json.dumps(results, ensure_ascii=False, indent=2))

def check_year(code):
    url = f'http://d.10jqka.com.cn/v6/line/bk_{code}/01/2026.js'
    try:
        raw = datafeed.http_get(url, headers={'Referer': 'http://q.10jqka.com.cn/'}, encoding='gbk', timeout=6, retry=0)
        match = re.search(r'\((.*)\)\s*;?\s*$', raw.strip(), re.S)
        obj = json.loads(match.group(1))
        dates = [item.split(',')[0] for item in (obj.get('data') or '').split(';') if item.strip()]
        return dict(code=code, source='2026.js', name=obj.get('name'), last_date=dates[-1] if dates else None, rows=len(dates))
    except Exception as error:
        return dict(code=code, source='2026.js', error=str(error))

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    print(json.dumps(list(pool.map(check_year, [r['code'] for r in results if r['asof'] != asof])), ensure_ascii=False))
