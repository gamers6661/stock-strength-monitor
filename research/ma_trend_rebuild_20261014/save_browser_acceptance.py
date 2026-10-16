import csv
import io
import json
from pathlib import Path

root = Path(__file__).resolve().parent
lines = (root / 'browser_acceptance.txt').read_text(encoding='utf-8-sig').splitlines()
result = json.loads(next(line for line in lines if line.startswith('{"base":')))
assert result['base']['ids'] == result['base']['backend']
assert result['filtered']['ids'] == result['filtered']['backend']
assert result['composition'] and result['emotion']['unchanged']
export = result['exportResult']
content = export.pop('text')
(root / 'served_sample.csv').write_text(content, encoding='utf-8-sig')
rows = list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
assert [row['代码'] for row in rows] == export['codes']
assert float(rows[0]['本阶段支撑触线价']) == result['details']['support']
assert all(row['均线版本'] == result['base']['version'] for row in rows)
assert all(row['UI版本'] == result['base']['generation'] for row in rows)
export['parsed_rows'] = len(rows)
export['same_support_as_detail'] = True
(root / 'http_acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'generation': result['base']['generation'], 'counts': result['base']['counts'],
                  'list_detail_csv': True, 'composition': True, 'emotion_rows': result['emotion']['rows']}, ensure_ascii=False))
