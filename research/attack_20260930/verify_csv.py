"""核对页面真实导出函数产生的全池CSV；先运行 verify_csv.cjs。"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


def run():
    with (OUT/'verified_export.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    header = rows[0]
    assert len(header) == len(set(header)), '列名重复'
    assert all(len(r) == len(header) for r in rows[1:]), '表头和数据列数不一致'
    data = {r[0]:dict(zip(header,r)) for r in rows[1:]}
    snap = json.loads((ROOT/'cache/snapshot.json').read_text(encoding='utf-8'))
    for row in snap['stocks']:
        item = data[row['code']]
        for n,label in ((5,'5日攻击速度分'),(10,'10日推进分'),(20,'20日涨幅基础分')):
            assert float(item[label]) == row['stock_strength_parts'][f'attack{n}']
        assert item['关注层级'] == str(row.get('trend_tier') or '')
        assert item['同花顺题材关系'] == '、'.join(t['name'] for t in row.get('theme_relations',[]))
        assert item['盘中暂态进攻档'] == str(row.get('live_attack_tier') or '')
        assert item['进攻监测候选'] == ('是' if row.get('attack_watch_candidate') else '否')
        assert item['当前报价状态'] == ('报价有效' if row.get('intraday_quote_fresh') is True
                                       else row.get('intraday_quote_status'))
    result = {'rows':len(rows)-1,'columns':len(header),'valid':True,
              'input_generated_at':snap['generated_at'],
              'method':'执行页面实际exportCSV函数并用标准CSV解析器逐行核对；下载落盘通道另记限制'}
    (OUT/'csv_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(result)


if __name__=='__main__':
    run()
