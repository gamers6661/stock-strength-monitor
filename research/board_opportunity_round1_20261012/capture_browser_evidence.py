import gzip
import json
import sys
from pathlib import Path

HERE=Path(__file__).parent
sys.path.insert(0,str(HERE.parents[1]))
import ui_payload
import board_opportunity

text=(HERE/'browser_result.txt').read_text(encoding='utf-8-sig')
evidence,_=json.JSONDecoder().raw_decode(text.split('### Result',1)[1].lstrip())
snapshot=ui_payload.full(evidence['generation'])
assert snapshot['board_opportunity_model']['counts']==evidence['counts']
evidence['backend_validation']=board_opportunity.validate(snapshot)
export=json.loads((HERE/'browser_board_export.json').read_text(encoding='utf-8-sig'))
by_id={b['id']:b for b in snapshot['board_catalog']}
for row in export['rows']:
    assert row['opportunity']==by_id[row['id']]['opportunity']
    assert row['member_codes']==by_id[row['id']]['member_codes']
expected=[i for i in snapshot['board_opportunity_model']['lists']['daily'] if by_id[i]['type']=='industry']
assert [r['id'] for r in export['rows']]==expected
evidence['export_equal']=True
evidence['export_rows']=len(expected)
evidence['snapshot_at']=snapshot['generated_at']
evidence['quote_capture_at']=snapshot['quote_capture_at']
(HERE/'browser_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
with gzip.open(HERE/'browser_snapshot.json.gz','wt',encoding='utf-8') as f:
    json.dump(snapshot,f,ensure_ascii=False,separators=(',',':'))
print(json.dumps({k:evidence[k] for k in ('generation','counts','snapshot_at','errors','export_equal','export_rows')},ensure_ascii=False))
