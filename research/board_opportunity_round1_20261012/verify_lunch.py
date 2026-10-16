import gzip,json,sys
from pathlib import Path
from urllib.request import urlopen
HERE=Path(__file__).parent;sys.path.insert(0,str(HERE.parents[1]))
import config,board_opportunity as B
with gzip.open(HERE/'accepted_snapshot.json.gz','rt',encoding='utf-8') as f:morning=json.load(f)
current=json.loads(config.SNAPSHOT_JSON.read_text(encoding='utf-8'))
assert current['session']=='午间休市',current['session']
old={b['id']:b['opportunity'] for b in morning['board_catalog']}
for b in current['board_catalog']:
    o=b['opportunity'];p=old[b['id']]
    assert o.get('retained') is True
    for key in ('current','qualifications','startup_confirmation','restart_confirmation','daily','background'):
        assert o[key]==p[key],(b['id'],key)
assert current['board_opportunity_model']['market']==morning['board_opportunity_model']['market']
assert current['board_opportunity_model']['quote_audit']==morning['board_opportunity_model']['quote_audit']
assert current['board_opportunity_model']['counts']==morning['board_opportunity_model']['counts']
B.validate(current)
status=json.loads(urlopen('http://127.0.0.1:8848/__status').read())
evidence=dict(session=current['session'],snapshot_at=current['generated_at'],generation=status['ui_generation'],
              retained_boards=len(old),counts=current['board_opportunity_model']['counts'],
              confirmation_unchanged=True,metrics_market_audit_unchanged=True,
              retained_until=current['board_opportunity_model']['retained_until'])
(HERE/'lunch_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
