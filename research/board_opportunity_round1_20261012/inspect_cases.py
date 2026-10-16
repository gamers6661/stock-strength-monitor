import gzip,json
from pathlib import Path
HERE=Path(__file__).parent
with gzip.open(HERE/'accepted_snapshot.json.gz','rt',encoding='utf-8') as f:s=json.load(f)
names=('风电设备','出版','电池','化妆品','国有大型银行Ⅱ')
print(json.dumps({'at':s['generated_at'],'market':s['board_opportunity_model']['market'],'counts':s['board_opportunity_model']['counts']},ensure_ascii=False))
for b in s['board_catalog']:
 if b['name'] in names:
  o=b['opportunity']
  print(json.dumps({'id':b['id'],'status':o['status'],'daily':o['daily'],'current':o['current'],'qualifications':o['qualifications'],'startup':o['startup_confirmation'],'restart':o['restart_confirmation'],'background':o['background'],'failed':o['failed_reasons'],'index':b.get('index_current')},ensure_ascii=False))
