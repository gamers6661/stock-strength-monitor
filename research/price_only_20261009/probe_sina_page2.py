"""新浪第二次只读核验：确认分页能向前覆盖，不接入正式服务。"""
import json
from pathlib import Path
from urllib.request import Request,urlopen

root=Path(__file__).parent
raw=(root/'news_sina_probe.json').read_text(encoding='utf-8-sig').lstrip()
previous,_=json.JSONDecoder().raw_decode(raw)
url='https://app.cj.sina.com.cn/api/news/pc?page=2&size=50&tag=0'
try:
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:
        payload=json.loads(response.read().decode('utf-8'))
    (root/'news_sina_page2_raw.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    rows=payload.get('result',{}).get('data',{}).get('feed',{}).get('list',[])
    old_ids={str(x['id']) for x in previous}
    result=dict(url=url,count=len(rows),first=rows[0].get('create_time') if rows else None,
                last=rows[-1].get('create_time') if rows else None,
                older_than_first_page=bool(rows and rows[-1].get('create_time','')<previous[-1]['time']),
                overlapping_ids=sum(str(r.get('id')) in old_ids for r in rows),
                item_keys=sorted(rows[0]) if rows else [])
except Exception as exc:
    result=dict(url=url,error=str(exc),result='分页未完成验证，不承诺可自动补全')
(root/'news_sina_page2_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
