"""方案阶段一次性只读核验，不接入服务或创建采集任务。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES={
    'miit_mobile':'https://wap.miit.gov.cn/zwgk/',
    'ndrc_notice':'https://www.ndrc.gov.cn/xxgk/zcfb/tz/',
    'stats_release':'https://www.stats.gov.cn/sj/zxfb/',
    'gov_policy':'https://www.gov.cn/zhengce/zuixin/',
}

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='a' and d.get('href'):
            self.links.append(d['href'])

def probe(item):
    name,url=item
    try:
        req=Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urlopen(req,timeout=15) as response:
            raw=response.read()
            encoding=response.headers.get_content_charset() or 'utf-8'
            page=raw.decode(encoding,errors='replace')
            parser=Links();parser.feed(page)
            (Path(__file__).parent/(name+'_sample.html')).write_text(page,encoding='utf-8')
            return dict(source=name,url=url,status=response.status,bytes=len(raw),
                        links=len(parser.links),article_links=sum('/art/' in x or '.html' in x or '.shtml' in x for x in parser.links),
                        battery_document='新型电池' in page,
                        result='仅验证返回及链接；是否覆盖完整、持续更新仍待适配验收')
    except Exception as exc:
        return dict(source=name,url=url,error=str(exc),result='本次不可直接获取，不列为稳定采集源')

with ThreadPoolExecutor(max_workers=4) as pool:
    result=dict(checked_at=datetime.now().isoformat(timespec='seconds'),sources=list(pool.map(probe,SOURCES.items())))
Path(__file__).with_name('news_page_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
