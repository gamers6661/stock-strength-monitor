"""Compare actual browser rows and downloaded CSV to backend eligibility/order."""
import csv
import json
from pathlib import Path

root = Path(__file__).parent
s = json.loads((root / 'baseline/snapshot.json').read_text('utf8'))
p = json.loads((root / 'ui_observed.json').read_text('utf8'))
lists = s['market_strength']['stocks']
boards = s['board_catalog']
publication = next(b for b in boards if b['name'] == '出版' and b['type'] == 'industry')
theme = next(b for b in boards if b['name'] == '知识产权保护' and b['type'] == 'theme')
members = set(publication['member_codes'])
intersection = members & set(theme['member_codes'])

def expected(axis, scope, codes=None, limit=None):
    result = [c for c in lists['sorts'][axis] if c in lists[scope] and (codes is None or c in codes)]
    return result[:limit] if limit else result

assert p['trend'] == expected('trend', 'trend', limit=100)
assert p['emotion'] == expected('emotion', 'emotion', limit=100)
assert p['publishTrend'] == expected('trend', 'trend', members)
assert p['intersectionTrend'] == expected('trend', 'trend', intersection)
assert p['intersectionEmotion'] == expected('emotion', 'emotion', intersection)
assert p['both'] == expected('emotion', 'both', intersection)
assert p['allMembers'] == expected('emotion', 'all', intersection)
exported = list(csv.DictReader((root / 'filtered_export.csv').open(encoding='utf-8-sig', newline='')))
assert [r['代码'] for r in exported] == p['allMembers']
air = next(b for b in boards if b['name'] == '航空装备Ⅱ' and b['type'] == 'industry')
assert p['overviewLink']['selected'] == 'true'
assert p['overviewLink']['directions'] == '航空装备Ⅱ ×'
assert p['overviewLink']['ids'] == expected('emotion', 'emotion', set(air['member_codes']))
assert p['chart']['width'] > 0 and p['chart']['height'] > 0
result = dict(passed=True, independent_lists=True, direction_intersection=True,
              csv_rows=len(exported), overview_link=True, chart=True)
(root / 'ui_acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
print(result)
