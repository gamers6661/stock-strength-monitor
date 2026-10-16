import csv,io,json
from pathlib import Path
root=Path(__file__).resolve().parent
lines=(root/'browser_acceptance.txt').read_text(encoding='utf-8-sig').splitlines()
result=json.loads(next(line for line in lines if line.startswith('{"base":')))
export=result['exportResult'];content=export.pop('text')
(root/'served_sample.csv').write_text(content,encoding='utf-8-sig')
rows=list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
assert [r['代码'] for r in rows]==export['codes']
assert all(r['均线版本']==result['base']['version'] for r in rows)
assert all(r['UI版本']==export['generation'] for r in rows)
assert [float(r['本阶段支撑触线价']) for r in rows]==[r['support'] for r in export['rows']]
assert all(json.loads(r['完整均线依据'])['support_price']==float(r['本阶段支撑触线价']) for r in rows)
export['same_support_and_generation']=True
(root/'http_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'version':result['base']['version'],'hash':result['base']['hash'],
                  'source':result['base']['source'],'counts':result['base']['counts'],
                  'source_age_max':max(result['base']['sourceAges'],default=None),
                  'detail_folded_after_chart':True,'csv_verified':True,'composition':result['composition']},ensure_ascii=False))
