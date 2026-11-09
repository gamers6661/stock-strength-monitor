"""Read-only same-input audit of repair observation versus previous selection."""
import copy,importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import stock_selection as S
import stock_selection_data as D
root=Path(__file__).resolve().parent
snap=json.loads(S.config.SNAPSHOT_JSON.read_text(encoding='utf8'))
snap['_security_master']=S.read('security_master.json').get('stocks',{})
snap['_universe_at']=str(snap['quote_capture_at'])[:10]
h,cal=S.inputs(snap);records=D.load();previous=S.read('state.json')
now=S.parse_at(snap['quote_capture_at'])
new=S.build(copy.deepcopy(snap),h,cal,copy.deepcopy(previous),records,now=now)
loader=__import__('importlib.machinery',fromlist=['SourceFileLoader']).SourceFileLoader('old_selection',str(root/'stock_selection.py.before'))
spec=importlib.util.spec_from_loader(loader.name,loader);old=importlib.util.module_from_spec(spec)
# Execute source with production __file__; calculations are the saved previous source.
old.__file__=S.__file__;exec(compile((root/'stock_selection.py.before').read_text(encoding='utf8'),S.__file__,'exec'),old.__dict__)
before=old.build(copy.deepcopy(snap),h,cal,copy.deepcopy(previous),records,now=now)
assert {c for c,x in before['items'].items() if x['eligible']}=={c for c,x in new['items'].items() if x['eligible']}
assert all(before['items'][c]['score']==x['score'] for c,x in new['items'].items())
rows=[x for x in new['items'].values() if x.get('observation_only')]
assert all(not x['eligible'] and x['intraday']['available'] and x['gates'][0]['passed'] for x in rows)
report=dict(source_at=new['source_at'],counts=new['counts'],original_eligibility_unchanged=True,scores_unchanged=True,
 observations=[dict(code=x['code'],name=x['name'],score=x['score'],state=x['intraday']['state'],evidence=x['repair_observation']) for x in rows],
 demingli=new['items'].get('001309'))
(root/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(source_at=new['source_at'],counts=new['counts'],unchanged=True,demingli=report['demingli']['repair_observation']),ensure_ascii=False))
