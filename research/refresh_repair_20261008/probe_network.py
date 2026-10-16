import concurrent.futures
import json
import time
import urllib.request

URLS = [
    'https://qt.gtimg.cn/q=sh600241,sh603867',
    'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?node=hs_a',
]

def probe(pair):
    url, direct = pair
    started = time.monotonic()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if direct else urllib.request.build_opener()
        response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=6)
        raw = response.read(240).decode('gbk', errors='replace')
        return dict(url=url, direct=direct, seconds=round(time.monotonic() - started, 2), body=raw)
    except Exception as error:
        return dict(url=url, direct=direct, seconds=round(time.monotonic() - started, 2), error=str(error))

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(probe, [(url, direct) for url in URLS for direct in (False, True)]))
print(json.dumps(results, ensure_ascii=False, indent=2))
print(json.dumps(urllib.request.getproxies(), ensure_ascii=False))
