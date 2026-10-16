"""只读整理本轮证据；不触发计算、采样或历史回填。"""
import csv,difflib,gzip,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
OUT=Path(__file__).resolve().parent;BEFORE=OUT/'before'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def gz(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
changes=[];diffdir=OUT/'diffs';diffdir.mkdir(exist_ok=True)
for path in sorted(ROOT.iterdir()):
    if not path.is_file() or (path.suffix not in ('.py','.js') and path.name!='dashboard_template.html'):continue
    old=BEFORE/path.name
    if old.exists() and old.read_bytes()==path.read_bytes():continue
    previous=old.read_text(encoding='utf-8-sig') if old.exists() else ''
    current=path.read_text(encoding='utf-8-sig')
    delta=''.join(difflib.unified_diff(previous.splitlines(True),current.splitlines(True),fromfile='before/'+path.name,tofile=path.name))
    (diffdir/(path.name+'.diff')).write_text(delta,encoding='utf-8')
    changes.append(dict(file=path.name,action='修改' if old.exists() else '新增',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),before_sha256=hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None))
save('changed_files.json',changes)
def rows(snap):
    result={r['code']:r for r in snap.get('coverage_catalog',[])};result.update({r['code']:r for r in snap.get('stocks',[])});return result
def reasons(name,snapshot):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['代码','名称','日线档','原进攻候选','原初步启动','新状态','主标签','全部标签','R0%','E0百分点','逐类未通过或未知原因','冻结事件及收盘复核'])
        allrows=rows(snapshot)
        for code in sorted(allrows):
            row=allrows[code];r=row.get('radar_opportunity')
            if not r:continue
            w.writerow([code,row.get('name'),row.get('trend_tier'),row.get('attack_watch_candidate'),row.get('startup_candidate'),r['status'],r['main_label'],'、'.join(r['labels']),r['R0'],r['E0'],json.dumps(r['reasons'],ensure_ascii=False),json.dumps({k:dict(event=v.get('event'),close_review=v.get('close_review')) for k,v in r['categories'].items()},ensure_ascii=False)])
frozen=gz(OUT/'final_frozen_result.json.gz');reasons('frozen_all_reasons.csv',frozen)
save('baseline_lists.json',dict(data_version=1791783657739203500,generated_at=frozen['generated_at'],quote_capture_at=frozen['quote_capture_at'],daily_tiers={tier:[c for c,r in rows(frozen).items() if r.get('trend_tier')==tier] for tier in ('A','B','C')},intraday_lists={key:[c for c,r in rows(frozen).items() if r.get(key)] for key in ('current_strong_candidate','current_pullback_candidate','turn_weak_repair_candidate','attack_watch_candidate','startup_candidate')}))
receipt=read(OUT/'final_published_refresh.json');published=gz(OUT/'final_published_refresh_snapshot.json.gz');reasons('published_all_reasons.csv',published)
save('published_lists.json',dict(data_version=receipt['after']['data_version'],generation=receipt['after']['ui_generation'],generated_at=published['generated_at'],daily_asof=published['strength_model']['asof'],market=published['radar_opportunity']['market'],lists=published['radar_opportunity']['lists'],counts=published['radar_opportunity']['counts'],close_review=published['radar_opportunity'].get('close_review'),legacy_lists={key:[c for c,r in rows(published).items() if r.get(key)] for key in ('attack_watch_candidate','startup_candidate')},daily_tiers={tier:[c for c,r in rows(published).items() if r.get('trend_tier')==tier] for tier in ('A','B','C')}))
intraday=gz(OUT/'accepted_refresh_snapshot.json.gz');ir=intraday['radar_opportunity'];candidates=[r for r in rows(intraday).values() if r.get('radar_opportunity',{}).get('current')]
representatives={}
for label,predicate in [('非A突破',lambda r:r.get('trend_tier')!='A' and '突破启动' in r['radar_opportunity']['labels']),('昨日A突破',lambda r:r.get('trend_tier')=='A' and '突破启动' in r['radar_opportunity']['labels']),('非A再启动',lambda r:r.get('trend_tier')!='A' and '强势再启动' in r['radar_opportunity']['labels']),('持续进攻',lambda r:'持续进攻' in r['radar_opportunity']['labels']),('观察受限',lambda r:r['radar_opportunity']['trade_restriction'])]:
    sample=next((r for r in candidates if predicate(r)),None);representatives[label]=dict(code=sample['code'],name=sample['name'],daily_tier=sample.get('trend_tier'),opportunity=sample['radar_opportunity']) if sample else None
down=next((r for r in rows(intraday).values() if r.get('trend_tier')=='A' and isinstance(r.get('radar_opportunity',{}).get('R0'),(int,float)) and r['radar_opportunity']['R0']<0),None)
representatives['下跌A不入池']=dict(code=down['code'],name=down['name'],opportunity=down['radar_opportunity']) if down else None
save('real_intraday_examples.json',dict(generated_at=intraday['generated_at'],receipt=read(OUT/'accepted_refresh.json')['after']['data_version'],counts=ir['counts'],lists=ir['lists'],examples=representatives))
browser=read(OUT/'browser_evidence.json');assert browser['generation']==receipt['after']['ui_generation']
if browser.get('detail'):assert browser['detail']['opportunity']==rows(published)[browser['detail']['code']]['radar_opportunity']
csv_checks={};pubrows=rows(published)
daily_codes=[r['code'] for r in published['radar'][browser['daily_strategy']]['items'] if r['tier']=='A']
assert browser['daily_codes']==daily_codes
for name,filename,expected in [('current','current.csv',published['radar_opportunity']['lists']['current']+published['radar_opportunity']['lists']['limited']),('follow','follow.csv',sum((published['radar_opportunity']['lists'][s] for s in ('pending','warning','tracking')),[])),('empty','empty.csv',[]),('daily','daily-A.csv',daily_codes)]:
    with (ROOT/'output/playwright/radar-v1'/filename).open(encoding='utf-8-sig',newline='') as f:reader=csv.DictReader(f);download=list(reader);columns=reader.fieldnames
    codecol=next(k for k in columns if k in ('代码','股票代码'))
    assert [r[codecol] for r in download]==expected,(name,'代码及顺序不一致')
    for r in download:
        assert r['雷达数据版本']==browser['generation']
        assert json.loads(r['雷达事件与完整依据'])==pubrows[r[codecol]]['radar_opportunity']
    csv_checks[name]=dict(rows=len(download),columns=len(columns),same_generation=True,full_opportunity_equals_disk=True,codes=expected)
save('page_detail_csv_consistency.json',dict(generation=browser['generation'],data_version=receipt['after']['data_version'],browser_errors=browser['errors'],csv=csv_checks))
print(json.dumps(dict(changed_files=len(changes),published_counts=published['radar_opportunity']['counts'],csv=csv_checks),ensure_ascii=False))
